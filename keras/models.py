from __future__ import absolute_import
from __future__ import print_function
import numpy as np
import warnings
import pprint
from six.moves import range
import six

from . import backend as K
from . import optimizers
from . import objectives
from . import callbacks as cbks
from .utils.layer_utils import container_from_config
from .utils.layer_utils import model_summary
from .utils.generic_utils import Progbar
from .layers import containers


def standardize_y(y):
    if not hasattr(y, 'shape'):
        y = np.asarray(y)
    if len(y.shape) == 1:
        y = np.expand_dims(y, 1)
    return y


def batch_shuffle(index_array, batch_size):
    batch_count = int(len(index_array) / batch_size)
    # to reshape we need to be cleanly divisible by batch size
    # we stash extra items and reappend them after shuffling
    last_batch = index_array[batch_count * batch_size:]
    index_array = index_array[:batch_count * batch_size]
    index_array = index_array.reshape((batch_count, batch_size))
    np.random.shuffle(index_array)
    index_array = index_array.flatten()
    return np.append(index_array, last_batch)


def make_batches(size, batch_size):
    nb_batch = int(np.ceil(size / float(batch_size)))
    return [(i * batch_size, min(size, (i + 1) * batch_size)) for i in range(0, nb_batch)]


def standardize_X(X):
    if type(X) == list:
        return X
    else:
        return [X]


def slice_X(X, start=None, stop=None):
    '''
    '''
    if type(X) == list:
        if hasattr(start, '__len__'):
            # hdf5 dataset only support list object as indices
            if hasattr(start, 'shape'):
                start = start.tolist()
            return [x[start] for x in X]
        else:
            return [x[start:stop] for x in X]
    else:
        if hasattr(start, '__len__'):
            if hasattr(start, 'shape'):
                start = start.tolist()
            return X[start]
        else:
            return X[start:stop]


def weighted_objective(fn):
    def weighted(y_true, y_pred, weights, mask=None):
        '''
        '''
        # score_array has ndim >= 2
        score_array = fn(y_true, y_pred)
        if mask is not None:
            # mask should have the same shape as score_array
            score_array *= mask
            #  the loss per batch should be proportional
            #  to the number of unmasked sampled.
            score_array /= K.mean(mask, axis= -1, keepdims = True)

        # reduce score_array to 1D
        ndim = K.ndim(score_array)
        for d in range(ndim-1):
            score_array = K.mean(score_array, axis=-1)

        if weights is not None:
            score_array *= weights
        return K.mean(score_array)
    return weighted


def standardize_weights(y, sample_weight=None, class_weight=None):
    '''
    '''
    if sample_weight is not None:
        assert len(sample_weight) == len(y)
        return sample_weight.flatten()
    elif isinstance(class_weight, dict):
        if len(y.shape) > 2:
            raise Exception('class_weight not supported for '
                            '3+ dimensional targets.')
        if y.shape[1] > 1:
            y_classes = y.argmax(axis=1)
        elif y.shape[1] == 1:
            y_classes = np.reshape(y, y.shape[0])
        else:
            y_classes = y
        weights = np.asarray([class_weight[cls] for cls in y_classes])
        return weights
    else:
        return np.ones((y.shape[0],))


def model_from_yaml(yaml_string, custom_objects={}):
    '''
        Returns a model generated from a local yaml file,
        which is either created by hand or from to_yaml method
        of Sequential or Graph
    '''
    import yaml
    config = yaml.load(yaml_string)
    return model_from_config(config, custom_objects=custom_objects)


def model_from_json(json_string, custom_objects={}):
    import json
    config = json.loads(json_string)
    return model_from_config(config, custom_objects=custom_objects)


def model_from_config(config, custom_objects={}):
    '''
    '''
    model_name = config.get('name')
    if model_name not in {'Graph', 'Sequential'}:
        raise Exception('Unrecognized model:', model_name)

    # Create a container then set class to appropriate model
    model = container_from_config(config, custom_objects=custom_objects)
    if model_name == 'Graph':
        model.__class__ = Graph
    elif model_name == 'Sequential':
        model.__class__ = Sequential

    if 'optimizer' in config:
        # if it has an optimizer, the model is assumed to be compiled
        loss = config.get('loss')
        class_mode = config.get('class_mode')

        optimizer_params = dict([(k, v) for k, v in config.get('optimizer').items()])
        optimizer_name = optimizer_params.pop('name')
        optimizer = optimizers.get(optimizer_name, optimizer_params)

        if model_name == 'Sequential':
            model.compile(loss=loss, optimizer=optimizer,
                          class_mode=class_mode)
        elif model_name == 'Graph':
            model.compile(loss=loss, optimizer=optimizer)
    return model


def get_function_name(o):
    if isinstance(o, six.string_types):
        return o
    else:
        return o.__name__


class Model(object):
    '''Abstract base model class.
    '''
    def _fit(self, f, ins, out_labels=[], batch_size=128,
             nb_epoch=100, verbose=1, callbacks=[],
             val_f=None, val_ins=None, shuffle=True, metrics=[]):
        '''
            Abstract fit function for f(ins).
            Assume that f returns a list, labelled by out_labels.
        '''
        do_validation = False
        if val_f and val_ins:
            do_validation = True
            if verbose:
                print('Train on %d samples, validate on %d samples' %
                      (len(ins[0]), len(val_ins[0])))

        nb_train_sample = len(ins[0])
        index_array = np.arange(nb_train_sample)

        history = cbks.History()
        if verbose:
            callbacks = [history, cbks.BaseLogger()] + callbacks
        else:
            callbacks = [history] + callbacks
        callbacks = cbks.CallbackList(callbacks)

        callbacks._set_model(self)
        callbacks._set_params({
            'batch_size': batch_size,
            'nb_epoch': nb_epoch,
            'nb_sample': nb_train_sample,
            'verbose': verbose,
            'do_validation': do_validation,
            'metrics': metrics,
        })
        callbacks.on_train_begin()

        self.stop_training = False
        for epoch in range(nb_epoch):
            callbacks.on_epoch_begin(epoch)
            if shuffle == 'batch':
                index_array = batch_shuffle(index_array, batch_size)
            elif shuffle:
                np.random.shuffle(index_array)

            batches = make_batches(nb_train_sample, batch_size)
            for batch_index, (batch_start, batch_end) in enumerate(batches):
                batch_ids = index_array[batch_start:batch_end]
                try:
                    ins_batch = slice_X(ins, batch_ids)
                except TypeError:
                    raise Exception('TypeError while preparing batch. '
                                    'If using HDF5 input data, '
                                    'pass shuffle="batch".')
                batch_logs = {}
                batch_logs['batch'] = batch_index
                batch_logs['size'] = len(batch_ids)
                callbacks.on_batch_begin(batch_index, batch_logs)
                outs = f(ins_batch)
                if type(outs) != list:
                    outs = [outs]
                for l, o in zip(out_labels, outs):
                    batch_logs[l] = o

                callbacks.on_batch_end(batch_index, batch_logs)

                epoch_logs = {}
                if batch_index == len(batches) - 1:  # last batch
                    # validation
                    if do_validation:
                        # replace with self._evaluate
                        val_outs = self._test_loop(val_f, val_ins,
                                                   batch_size=batch_size,
                                                   verbose=0)
                        if type(val_outs) != list:
                            val_outs = [val_outs]
                        # same labels assumed
                        for l, o in zip(out_labels, val_outs):
                            epoch_logs['val_' + l] = o

            callbacks.on_epoch_end(epoch, epoch_logs)
            if self.stop_training:
                break

        callbacks.on_train_end()
        return history

    def _predict_loop(self, f, ins, batch_size=128, verbose=0):
        '''Abstract method to loop over some data in batches.
        '''
        nb_sample = len(ins[0])
        outs = []
        if verbose == 1:
            progbar = Progbar(target=nb_sample)
        batches = make_batches(nb_sample, batch_size)
        index_array = np.arange(nb_sample)
        for batch_index, (batch_start, batch_end) in enumerate(batches):
            batch_ids = index_array[batch_start:batch_end]
            ins_batch = slice_X(ins, batch_ids)

            batch_outs = f(ins_batch)
            if type(batch_outs) != list:
                batch_outs = [batch_outs]
            if batch_index == 0:
                for batch_out in batch_outs:
                    shape = (nb_sample,) + batch_out.shape[1:]
                    outs.append(np.zeros(shape))

            for i, batch_out in enumerate(batch_outs):
                outs[i][batch_start:batch_end] = batch_out
            if verbose == 1:
                progbar.update(batch_end)
        return outs

    def _test_loop(self, f, ins, batch_size=128, verbose=0):
        '''Abstract method to loop over some data in batches.
        '''
        nb_sample = len(ins[0])
        outs = []
        if verbose == 1:
            progbar = Progbar(target=nb_sample)
        batches = make_batches(nb_sample, batch_size)
        index_array = np.arange(nb_sample)
        for batch_index, (batch_start, batch_end) in enumerate(batches):
            batch_ids = index_array[batch_start:batch_end]
            ins_batch = slice_X(ins, batch_ids)

            batch_outs = f(ins_batch)
            if type(batch_outs) == list:
                if batch_index == 0:
                    for batch_out in enumerate(batch_outs):
                        outs.append(0.)
                for i, batch_out in enumerate(batch_outs):
                    outs[i] += batch_out * len(batch_ids)
            else:
                if batch_index == 0:
                    outs.append(0.)
                outs[0] += batch_outs * len(batch_ids)

            if verbose == 1:
                progbar.update(batch_end)
        for i, out in enumerate(outs):
            outs[i] /= nb_sample
        return outs

    def get_config(self, verbose=0):
        '''Return the configuration of the model
        as a dictionary.

        To load a model from its configuration, use
        `keras.models.model_from_config(config, custom_objects={})`.
        '''
        config = super(Model, self).get_config()
        for p in ['class_mode']:
            if hasattr(self, p):
                config[p] = getattr(self, p)
        if hasattr(self, 'optimizer'):
            config['optimizer'] = self.optimizer.get_config()
        if hasattr(self, 'loss'):
            if type(self.loss) == dict:
                config['loss'] = dict([(k, get_function_name(v)) for k, v in self.loss.items()])
            else:
                config['loss'] = get_function_name(self.loss)

        if verbose:
            pp = pprint.PrettyPrinter(indent=4)
            pp.pprint(config)
        return config

    def to_yaml(self, **kwargs):
        '''Return a yaml string containing the model configuration.

        To load a model from a yaml save file, use
        `keras.models.from_yaml(yaml_string, custom_objects={})`.

        `custom_objects` should be a dictionary mapping
        the names of custom losses / layers / etc to the corresponding
        functions / classes.
        '''
        import yaml
        config = self.get_config()
        return yaml.dump(config, **kwargs)

    def to_json(self, **kwargs):
        '''Return a JSON string containing the model configuration.

        To load a model from a JSON save file, use
        `keras.models.from_json(json_string, custom_objects={})`.
        '''
        import json
        config = self.get_config()
        return json.dumps(config, **kwargs)

    def summary(self):
        '''Print out a summary of the model architecture,
        include parameter count information.
        '''
        model_summary(self)


class Sequential(Model, containers.Sequential):
    '''Linear stack of layers.

    Inherits from containers.Sequential.
    '''
    def compile(self, optimizer, loss,
                class_mode="categorical"):
        '''Configure the learning process.

        # Arguments
            optimizer: str (name of optimizer) or optimizer object.
                See [optimizers](optimizers.md).
            loss: str (name of objective function) or objective function.
                See [objectives](objectives.md).
            class_mode: one of "categorical", "binary".
                This is only used for computing classification accuracy or
                using the predict_classes method.
        '''
        self.optimizer = optimizers.get(optimizer)

        self.loss = objectives.get(loss)
        weighted_loss = weighted_objective(objectives.get(loss))

        # input of model
        self.X_train = self.get_input(train=True)
        self.X_test = self.get_input(train=False)

        self.y_train = self.get_output(train=True)
        self.y_test = self.get_output(train=False)

        # target of model
        self.y = K.placeholder(ndim=K.ndim(self.y_train))
        # weights: one scalar per sample
        self.weights = K.placeholder(ndim=1)

        if hasattr(self.layers[-1], "get_output_mask"):
            mask = self.layers[-1].get_output_mask()
        else:
            mask = None
        train_loss = weighted_loss(self.y, self.y_train, self.weights, mask)
        test_loss = weighted_loss(self.y, self.y_test, self.weights, mask)

        if class_mode == "categorical":
            train_accuracy = K.mean(K.equal(K.argmax(self.y, axis=-1),
                                            K.argmax(self.y_train, axis=-1)))
            test_accuracy = K.mean(K.equal(K.argmax(self.y, axis=-1),
                                           K.argmax(self.y_test, axis=-1)))

        elif class_mode == "binary":
            train_accuracy = K.mean(K.equal(self.y, K.round(self.y_train)))
            test_accuracy = K.mean(K.equal(self.y, K.round(self.y_test)))
        else:
            raise Exception("Invalid class mode:" + str(class_mode))
        self.class_mode = class_mode

        for r in self.regularizers:
            train_loss = r(train_loss)
        updates = self.optimizer.get_updates(self.params,
                                             self.constraints,
                                             train_loss)
        updates += self.updates

        if type(self.X_train) == list:
            train_ins = self.X_train + [self.y, self.weights]
            test_ins = self.X_test + [self.y, self.weights]
            assert type(self.X_test) == list
            predict_ins = self.X_test
        else:
            train_ins = [self.X_train, self.y, self.weights]
            test_ins = [self.X_test, self.y, self.weights]
            predict_ins = [self.X_test]

        self._train = K.function(train_ins, [train_loss], updates=updates)
        self._train_with_acc = K.function(train_ins, [train_loss, train_accuracy], updates=updates)
        self._predict = K.function(predict_ins, [self.y_test], updates=self.state_updates)
        self._test = K.function(test_ins, [test_loss])
        self._test_with_acc = K.function(test_ins, [test_loss, test_accuracy])

    def fit(self, X, y, batch_size=128, nb_epoch=100, verbose=1, callbacks=[],
            validation_split=0., validation_data=None, shuffle=True,
            show_accuracy=False, class_weight=None, sample_weight=None):
        '''Train the model for a fixed number of epochs.

        Returns a history object. It `history` attribute is a record of
        training loss values at successive epochs,
        as well as validation loss values (if applicable).

        # Arguments
            X: data, as a numpy array.
            y: labels, as a numpy array.
            batch_size: int. Number of samples per gradient update.
            nb_epoch: int.
            verbose: 0 for no logging to stdout,
                1 for progress bar logging, 2 for one log line per epoch.
            callbacks: `keras.callbacks.Callback` list.
                List of callbacks to apply during training.
                See [callbacks](callbacks.md).
            validation_split: float (0. < x < 1).
                Fraction of the data to use as held-out validation data.
            validation_data: tuple (X, y) to be used as held-out
                validation data. Will override validation_split.
            shuffle: boolean or str (for 'batch').
                Whether to shuffle the samples at each epoch.
                'batch' is a special option for dealing with the
                limitations of HDF5 data; it shuffles in batch-sized chunks.
            show_accuracy: boolean. Whether to display
                class accuracy in the logs to stdout at each epoch.
            class_weight: dictionary mapping classes to a weight value,
                used for scaling the loss function (during training only).
            sample_weight: list or numpy array with 1:1 mapping to
                the training samples, used for scaling the loss function
                (during training only). For time-distributed data,
                there is one weight per sample *per timestep*,
                i.e. if your output data is shaped
                `(nb_samples, timesteps, output_dim)`,
                your mask should be of shape `(nb_samples, timesteps, 1)`.
                This allows you to mask out or reweight individual
                output timesteps, which is useful
                in sequence to sequence learning.
        '''
        X = standardize_X(X)
        y = standardize_y(y)

        val_f = None
        val_ins = None
        if validation_data or validation_split:
            if show_accuracy:
                val_f = self._test_with_acc
            else:
                val_f = self._test
        if validation_data:
            if len(validation_data) == 2:
                X_val, y_val = validation_data
                X_val = standardize_X(X_val)
                y_val = standardize_y(y_val)
                sample_weight_val = standardize_weights(y_val)
            elif len(validation_data) == 3:
                X_val, y_val, sample_weight_val = validation_data
                X_val = standardize_X(X_val)
                y_val = standardize_y(y_val)
                sample_weight_val = standardize_weights(y_val,
                                                        sample_weight=sample_weight_val)
            else:
                raise Exception('Invalid format for validation data; '
                                'provide a tuple (X_val, y_val) or '
                                '(X_val, y_val, sample_weight). '
                                'X_val may be a numpy array or a list of '
                                'numpy arrays depending on your model input.')
            val_ins = X_val + [y_val, sample_weight_val]

        elif 0 < validation_split < 1:
            split_at = int(len(X[0]) * (1 - validation_split))
            X, X_val = (slice_X(X, 0, split_at), slice_X(X, split_at))
            y, y_val = (slice_X(y, 0, split_at), slice_X(y, split_at))
            if sample_weight is not None:
                sample_weight, sample_weight_val = (slice_X(sample_weight, 0, split_at), slice_X(sample_weight, split_at))
                sample_weight_val = standardize_weights(y_val,
                                                        sample_weight=sample_weight_val)
            else:
                sample_weight_val = standardize_weights(y_val)
            val_ins = X_val + [y_val, sample_weight_val]

        if show_accuracy:
            f = self._train_with_acc
            out_labels = ['loss', 'acc']
        else:
            f = self._train
            out_labels = ['loss']

        sample_weight = standardize_weights(y, class_weight=class_weight,
                                            sample_weight=sample_weight)
        ins = X + [y, sample_weight]
        metrics = ['loss', 'acc', 'val_loss', 'val_acc']
        return self._fit(f, ins, out_labels=out_labels,
                         batch_size=batch_size, nb_epoch=nb_epoch,
                         verbose=verbose, callbacks=callbacks,
                         val_f=val_f, val_ins=val_ins,
                         shuffle=shuffle, metrics=metrics)

    def predict(self, X, batch_size=128, verbose=0):
        '''Generate output predictions for the input samples
        batch by batch.

        # Arguments
            X: the input data, as a numpy array.
            batch_size: integer.
            verbose: verbosity mode, 0 or 1.

        # Returns
            A numpy array of predictions.
        '''
        X = standardize_X(X)
        return self._predict_loop(self._predict, X, batch_size, verbose)[0]

    def predict_proba(self, X, batch_size=128, verbose=1):
        '''Generate class probability predictions for the input samples
        batch by batch.

        # Arguments
            X: the input data, as a numpy array.
            batch_size: integer.
            verbose: verbosity mode, 0 or 1.

        # Returns
            A numpy array of probability predictions.
        '''
        preds = self.predict(X, batch_size, verbose)
        if preds.min() < 0 or preds.max() > 1:
            warnings.warn('Network returning invalid probability values.')
        return preds

    def predict_classes(self, X, batch_size=128, verbose=1):
        '''Generate class predictions for the input samples
        batch by batch.

        # Arguments
            X: the input data, as a numpy array.
            batch_size: integer.
            verbose: verbosity mode, 0 or 1.

        # Returns
            A numpy array of class predictions.
        '''
        proba = self.predict(X, batch_size=batch_size, verbose=verbose)
        if self.class_mode == 'categorical':
            return proba.argmax(axis=-1)
        else:
            return (proba > 0.5).astype('int32')

    def evaluate(self, X, y, batch_size=128, show_accuracy=False,
                 verbose=1, sample_weight=None):
        '''Compute the loss on some input data, batch by batch.

        # Arguments
            X: input data, as a numpy array.
            y: labels, as a numpy array.
            batch_size: integer.
            show_accuracy: boolean.
            verbose: verbosity mode, 0 or 1.
            sample_weight: sample weights, as a numpy array.
        '''
        X = standardize_X(X)
        y = standardize_y(y)
        sample_weight = standardize_weights(y, sample_weight=sample_weight)

        ins = X + [y, sample_weight]
        if show_accuracy:
            f = self._test_with_acc
        else:
            f = self._test
        outs = self._test_loop(f, ins, batch_size, verbose)
        if show_accuracy:
            return outs
        else:
            return outs[0]

    def train_on_batch(self, X, y, accuracy=False,
                       class_weight=None, sample_weight=None):
        '''Single gradient update over one batch of samples.

        Returns the loss over the data,
        or a tuple `(loss, accuracy)` if `accuracy=True`.

        Arguments: see `fit` method.
        '''
        X = standardize_X(X)
        y = standardize_y(y)
        sample_weight = standardize_weights(y, class_weight=class_weight,
                                            sample_weight=sample_weight)
        ins = X + [y, sample_weight]
        if accuracy:
            return self._train_with_acc(ins)
        else:
            return self._train(ins)

    def test_on_batch(self, X, y, accuracy=False, sample_weight=None):
        '''Returns the loss over a single batch of samples,
        or a tuple `(loss, accuracy)` if `accuracy=True`.

        Arguments: see `fit` method.
        '''
        X = standardize_X(X)
        y = standardize_y(y)
        sample_weight = standardize_weights(y, sample_weight=sample_weight)

        ins = X + [y, sample_weight]
        if accuracy:
            return self._test_with_acc(ins)
        else:
            return self._test(ins)

    def predict_on_batch(self, X):
        '''Returns predictions for a single batch of samples.
        '''
        ins = standardize_X(X)
        return self._predict(ins)

    def save_weights(self, filepath, overwrite=False):
        '''Dump all layer weights to a HDF5 file.
        '''
        import h5py
        import os.path
        # if file exists and should not be overwritten
        if not overwrite and os.path.isfile(filepath):
            import sys
            get_input = input
            if sys.version_info[:2] <= (2, 7):
                get_input = raw_input
            overwrite = get_input('[WARNING] %s already exists - overwrite? '
                                  '[y/n]' % (filepath))
            while overwrite not in ['y', 'n']:
                overwrite = get_input('Enter "y" (overwrite) or "n" (cancel).')
            if overwrite == 'n':
                return
            print('[TIP] Next time specify overwrite=True in save_weights!')

        f = h5py.File(filepath, 'w')
        f.attrs['nb_layers'] = len(self.layers)
        for k, l in enumerate(self.layers):
            g = f.create_group('layer_{}'.format(k))
            weights = l.get_weights()
            g.attrs['nb_params'] = len(weights)
            for n, param in enumerate(weights):
                param_name = 'param_{}'.format(n)
                param_dset = g.create_dataset(param_name, param.shape,
                                              dtype=param.dtype)
                param_dset[:] = param
        f.flush()
        f.close()

    def load_weights(self, filepath):
        '''Load all layer weights from a HDF5 save file.
        '''
        import h5py
        f = h5py.File(filepath)
        for k in range(f.attrs['nb_layers']):
            # This method does not make use of Sequential.set_weights()
            # for backwards compatibility.
            g = f['layer_{}'.format(k)]
            weights = [g['param_{}'.format(p)] for p in range(g.attrs['nb_params'])]
            self.layers[k].set_weights(weights)
        f.close()


class Graph(Model, containers.Graph):
    '''Arbitrary connection graph.
    It can have any number of inputs and outputs,
    with each output trained with its own loss function.
    The quantity being optimized by a Graph model is
    the sum of all loss functions over the different outputs.

    Inherits from `containers.Graph`.
    '''
    def compile(self, optimizer, loss):
        '''Configure the learning process.

        # Arguments
            optimizer: str (name of optimizer) or optimizer object.
                See [optimizers](optimizers.md).
            loss: dictionary mapping the name(s) of the output(s) to
                a loss function (string name of objective function or
                objective function. See [objectives](objectives.md)).
        '''
        ys = []
        ys_train = []
        ys_test = []
        weights = []
        train_loss = 0.
        test_loss = 0.
        for output_name in self.output_order:
            loss_fn = loss[output_name]
            output = self.outputs[output_name]
            y_train = output.get_output(True)
            y_test = output.get_output(False)
            y = K.placeholder(ndim=K.ndim(y_train))
            ys.append(y)
            ys_train.append(y_train)
            ys_test.append(y_test)

            if hasattr(output, "get_output_mask"):
                mask = output.get_output_mask()
            else:
                mask = None

            weight = K.placeholder(ndim=1)
            weights.append(weight)
            weighted_loss = weighted_objective(objectives.get(loss_fn))
            train_loss += weighted_loss(y, y_train, weight, mask)
            test_loss += weighted_loss(y, y_test, weight, mask)

        ins = [self.inputs[name].input for name in self.input_order]
        train_ins = ins + ys + weights
        test_ins = ins + ys + weights

        for r in self.regularizers:
            train_loss = r(train_loss)
        self.optimizer = optimizers.get(optimizer)
        updates = self.optimizer.get_updates(self.params,
                                             self.constraints,
                                             train_loss)
        updates += self.updates
        self.loss = loss

        self._train = K.function(train_ins, [train_loss], updates=updates)
        self._test = K.function(test_ins, [test_loss])
        self._predict = K.function(inputs=ins, outputs=ys_test,
                                   updates=self.state_updates)

    def fit(self, data, batch_size=128, nb_epoch=100, verbose=1, callbacks=[],
            validation_split=0., validation_data=None, shuffle=True,
            class_weight={}, sample_weight={}):
        '''Train the model for a fixed number of epochs.

        Returns a history object. It `history` attribute is a record of
        training loss values at successive epochs,
        as well as validation loss values (if applicable).

        # Arguments
            data: dictionary mapping input names and outputs names to
                appropriate numpy arrays. All arrays should contain
                the same number of samples.
            batch_size: int. Number of samples per gradient update.
            nb_epoch: int.
            verbose: 0 for no logging to stdout,
                1 for progress bar logging, 2 for one log line per epoch.
            callbacks: `keras.callbacks.Callback` list. List of callbacks
                to apply during training. See [callbacks](callbacks.md).
            validation_split: float (0. < x < 1). Fraction of the data to
                use as held-out validation data.
            validation_data: dictionary mapping input names and outputs names
                to appropriate numpy arrays to be used as
                held-out validation data.
                All arrays should contain the same number of samples.
                Will override validation_split.
            shuffle: boolean. Whether to shuffle the samples at each epoch.
            class_weight: dictionary mapping output names to
                class weight dictionaries.
            sample_weight: dictionary mapping output names to
                numpy arrays of sample weights.
        '''
        X = [data[name] for name in self.input_order]
        y = [standardize_y(data[name]) for name in self.output_order]

        sample_weight_list = [standardize_weights(y[i],
                                                  sample_weight=sample_weight.get(self.output_order[i])) for i in range(len(self.output_order))]
        class_weight_list = [class_weight.get(name) for name in self.output_order]

        val_f = None
        val_ins = None
        if validation_data or validation_split:
            val_f = self._test
        if validation_data:
            # can't use sample weights with validation data at this point
            y_val = [standardize_y(validation_data[name]) for name in self.output_order]
            sample_weight = [standardize_weights(y_val[i]) for i in range(len(y_val))]
            val_ins = [validation_data[name] for name in self.input_order] + [standardize_y(validation_data[name]) for name in self.output_order] + sample_weight

        elif 0 < validation_split < 1:
            split_at = int(len(X[0]) * (1 - validation_split))
            X, X_val = (slice_X(X, 0, split_at), slice_X(X, split_at))
            y, y_val = (slice_X(y, 0, split_at), slice_X(y, split_at))
            sample_weight_list, sample_weight_list_val = (slice_X(sample_weight_list, 0, split_at), slice_X(sample_weight_list, split_at))
            val_ins = X_val + y_val + sample_weight_list_val

        f = self._train
        out_labels = ['loss']
        metrics = ['loss', 'val_loss']

        sample_weight_list = [standardize_weights(y[i],
                                                  sample_weight=sample_weight_list[i],
                                                  class_weight=class_weight_list[i]) for i in range(len(self.output_order))]
        ins = X + y + sample_weight_list
        history = self._fit(f, ins, out_labels=out_labels,
                            batch_size=batch_size, nb_epoch=nb_epoch,
                            verbose=verbose, callbacks=callbacks,
                            val_f=val_f, val_ins=val_ins,
                            shuffle=shuffle, metrics=metrics)
        return history

    def evaluate(self, data, batch_size=128, verbose=0, sample_weight={}):
        '''Compute the loss on some input data, batch by batch.

        Arguments: see `fit` method.
        '''
        sample_weight = [standardize_weights(data[name],
                                             sample_weight=sample_weight.get(name)) for name in self.output_order]

        ins = [data[name] for name in self.input_order] + [standardize_y(data[name]) for name in self.output_order] + sample_weight
        outs = self._test_loop(self._test, ins, batch_size, verbose)
        return outs[0]

    def predict(self, data, batch_size=128, verbose=0):
        '''Generate output predictions for the input samples
        batch by batch.

        Arguments: see `fit` method.
        '''
        ins = [data[name] for name in self.input_order]
        outs = self._predict_loop(self._predict, ins, batch_size, verbose)
        return dict(zip(self.output_order, outs))

    def train_on_batch(self, data, class_weight={}, sample_weight={}):
        '''Single gradient update on a batch of samples.

        Arguments: see `fit` method.
        '''
        sample_weight = [standardize_weights(data[name],
                                             sample_weight=sample_weight.get(name),
                                             class_weight=class_weight.get(name)) for name in self.output_order]
        ins = [data[name] for name in self.input_order] + [standardize_y(data[name]) for name in self.output_order] + sample_weight
        return self._train(ins)

    def test_on_batch(self, data, sample_weight={}):
        '''Compute the loss on a single batch of samples.

        Arguments: see `fit` method.
        '''
        sample_weight = [standardize_weights(data[name],
                                             sample_weight=sample_weight.get(name)) for name in self.output_order]
        ins = [data[name] for name in self.input_order] + [standardize_y(data[name]) for name in self.output_order] + sample_weight
        return self._test(ins)

    def predict_on_batch(self, data):
        '''Generate predictions for a single batch of samples.
        '''
        ins = [data[name] for name in self.input_order]
        return self._predict(ins)

    def save_weights(self, filepath, overwrite=False):
        '''Save weights from all layers to a HDF5 files.
        '''
        import h5py
        import os.path
        # if file exists and should not be overwritten
        if not overwrite and os.path.isfile(filepath):
            import sys
            get_input = input
            if sys.version_info[:2] <= (2, 7):
                get_input = raw_input
            overwrite = get_input('[WARNING] %s already exists - overwrite? '
                                  '[y/n]' % (filepath))
            while overwrite not in ['y', 'n']:
                overwrite = get_input('Enter "y" (overwrite) or "n" (cancel).')
            if overwrite == 'n':
                return
            print('[TIP] Next time specify overwrite=True in save_weights!')

        f = h5py.File(filepath, 'w')
        g = f.create_group('graph')
        weights = self.get_weights()
        g.attrs['nb_params'] = len(weights)
        for n, param in enumerate(weights):
            param_name = 'param_{}'.format(n)
            param_dset = g.create_dataset(param_name, param.shape,
                                          dtype=param.dtype)
            param_dset[:] = param
        f.flush()
        f.close()

    def load_weights(self, filepath):
        '''Load weights from a HDF5 file.
        '''
        import h5py
        f = h5py.File(filepath)
        g = f['graph']
        weights = [g['param_{}'.format(p)] for p in range(g.attrs['nb_params'])]
        self.set_weights(weights)
        f.close()
