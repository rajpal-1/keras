import copy
import inspect
import warnings

import tree

from keras import backend
from keras import ops
from keras.backend.common import global_state
from keras.layers import Dense
from keras.layers import Softmax
from keras.layers.convolutional.base_conv import BaseConv
from keras.layers.core.input_layer import Input
from keras.layers.core.input_layer import InputLayer
from keras.layers.input_spec import InputSpec
from keras.layers.layer import Layer
from keras.legacy.saving import saving_utils
from keras.legacy.saving import serialization as legacy_serialization
from keras.models.model import Model
from keras.ops.function import Function
from keras.ops.function import _build_map
from keras.ops.function import make_node_key
from keras.ops.node import Node
from keras.saving import serialization_lib
from keras.utils import tracking
from keras.utils.nest import pack_sequence_as


class Functional(Function, Model):
    """A `Functional` model is a `Model` defined as a directed graph of layers.

    Three types of `Model` exist: subclassed `Model`, `Functional` model,
    and `Sequential` (a special case of `Functional`).

    A `Functional` model can be instantiated by passing two arguments to
    `__init__()`. The first argument is the `keras.Input` objects
    that represent the inputs to the model.
    The second argument specifies the output tensors that represent
    the outputs of this model. Both arguments can be a nested structure
    of tensors.

    Example:

    ```
    inputs = {'x1': keras.Input(shape=(10,), name='x1'),
              'x2': keras.Input(shape=(1,), name='x2')}
    t = keras.layers.Dense(1, activation='relu')(inputs['x1'])
    outputs = keras.layers.Add()([t, inputs['x2']])
    model = keras.Model(inputs, outputs)
    ```

    A `Functional` model constructed using the Functional API can also
    include raw Keras 3 ops.

    Example:

    ```python
    inputs = keras.Input(shape=(10,))
    x = keras.layers.Dense(1)(inputs)
    outputs = ops.nn.relu(x)
    model = keras.Model(inputs, outputs)
    ```

    A new `Functional` model can also be created by using the
    intermediate tensors. This enables you to quickly extract sub-components
    of the model.

    Example:

    ```python
    inputs = keras.Input(shape=(None, None, 3))
    processed = keras.layers.RandomCrop(width=32, height=32)(inputs)
    conv = keras.layers.Conv2D(filters=2, kernel_size=3)(processed)
    pooling = keras.layers.GlobalAveragePooling2D()(conv)
    feature = keras.layers.Dense(10)(pooling)

    full_model = keras.Model(inputs, feature)
    backbone = keras.Model(processed, conv)
    activations = keras.Model(conv, feature)
    ```

    Note that the `backbone` and `activations` models are not
    created with `keras.Input` objects, but with the tensors
    that are originated from `keras.Input` objects.
    Under the hood, the layers and weights will
    be shared across these models, so that user can train the `full_model`, and
    use `backbone` or `activations` to do feature extraction.
    The inputs and outputs of the model can be nested structures of tensors as
    well, and the created models are standard `Functional` model that support
    all the existing API.

    Args:
        inputs: List of input tensors (must be created via `keras.Input()`
            or originated from `keras.Input()`).
        outputs: List of output tensors.
        name: String, optional. Name of the model.
        trainable: Boolean, optional. If the model's variables should be
            trainable.
    """

    @tracking.no_automatic_dependency_tracking
    def __init__(self, inputs, outputs, name=None, **kwargs):
        if isinstance(inputs, dict):
            for k, v in inputs.items():
                if not isinstance(v, backend.KerasTensor):
                    raise ValueError(
                        "When providing `inputs` as a dict, all values in the "
                        f"dict must be KerasTensors. Received: inputs={inputs} "
                        f"including invalid value {v} of type {type(v)}"
                    )
                if k != v.name:
                    warnings.warn(
                        "When providing `inputs` as a dict, all keys in the "
                        "dict must match the names of the corresponding "
                        f"tensors. Received key '{k}' mapping to value {v} "
                        f"which has name '{v.name}'. Change the tensor name to "
                        f"'{k}' (via `Input(..., name='{k}')`)"
                    )
        elif isinstance(inputs, (list, tuple)):
            for x in inputs:
                if not isinstance(x, backend.KerasTensor):
                    raise ValueError(
                        "When providing `inputs` as a list/tuple, all values "
                        f"in the list/tuple must be KerasTensors. Received: "
                        f"inputs={inputs} including invalid value {x} of type "
                        f"{type(x)}"
                    )
        elif not isinstance(inputs, backend.KerasTensor):
            raise ValueError(
                f"Unrecognized type for `inputs`: {inputs} "
                f"(of type {type(inputs)})"
            )
        if isinstance(outputs, dict):
            for k, v in outputs.items():
                if not isinstance(v, backend.KerasTensor):
                    raise ValueError(
                        "When providing `outputs` as a dict, all values in the "
                        f"dict must be KerasTensors. Received: "
                        f"outputs={outputs} including invalid value {v} of "
                        f"type {type(v)}"
                    )
        elif isinstance(outputs, (list, tuple)):
            for x in outputs:
                if not isinstance(x, backend.KerasTensor):
                    raise ValueError(
                        "When providing `outputs` as a list/tuple, all values "
                        f"in the list/tuple must be KerasTensors. Received: "
                        f"outputs={outputs} including invalid value {x} of "
                        f"type {type(x)}"
                    )
        elif not isinstance(outputs, backend.KerasTensor):
            raise ValueError(
                f"Unrecognized type for `outputs`: {outputs} "
                f"(of type {type(outputs)})"
            )

        trainable = kwargs.pop("trainable", None)
        validate_softmax = kwargs.pop("validate_output_activation", True)

        if not all([is_input_keras_tensor(t) for t in tree.flatten(inputs)]):
            inputs, outputs = clone_graph_nodes(inputs, outputs)

        Function.__init__(self, inputs, outputs, name=name, **kwargs)

        if trainable is not None:
            self.trainable = trainable

        self._layers = self.layers
        self.build(None)
        # We will convert directly (to the correct dtype per input).
        self._convert_input_args = False
        self._allow_non_tensor_positional_args = True
        output_layers = [x._keras_history[0] for x in self.outputs]
        self.output_names = [x.name for x in output_layers]

        if validate_softmax:
            layer_output_mapping = {
                layer.name: layer for layer in output_layers
            }
            _check_output_activation_softmax(layer_output_mapping)

    def _lock_state(self):
        # Unlike other layers, we allow Functional state to be mutable after
        # build. E.g. to attach a layer to a model that is not part of the
        # functional DAG.
        pass

    @property
    def layers(self):
        layers = []
        for operation in self._operations:
            if isinstance(operation, Layer):
                layers.append(operation)
        return layers

    def call(self, inputs, training=None, mask=None):
        # Add support for traning, masking
        inputs = self._standardize_inputs(inputs)
        if mask is None:
            masks = [None] * len(inputs)
        else:
            masks = self._flatten_to_reference_inputs(mask)
            for x, mask in zip(inputs, masks):
                if mask is not None:
                    x._keras_mask = mask
        outputs = self._run_through_graph(
            inputs, operation_fn=lambda op: operation_fn(op, training=training)
        )
        return unpack_singleton(outputs)

    def compute_output_spec(self, inputs, training=None, mask=None):
        # From Function
        return super().compute_output_spec(inputs)

    def build(self, input_shape):
        self.built = True

    @property
    def input_shape(self):
        input_shapes = tree.map_structure(lambda x: x.shape, self.inputs)
        if isinstance(input_shapes, list) and len(input_shapes) == 1:
            return input_shapes[0]
        return input_shapes

    @property
    def output_shape(self):
        output_shapes = tree.map_structure(lambda x: x.shape, self.outputs)
        if isinstance(output_shapes, list) and len(output_shapes) == 1:
            return output_shapes[0]
        return output_shapes

    def _assert_input_compatibility(self, *args):
        return super(Model, self)._assert_input_compatibility(*args)

    def _flatten_to_reference_inputs(self, inputs, allow_extra_keys=True):
        if isinstance(inputs, dict):
            ref_inputs = self._inputs_struct
            if not tree.is_nested(ref_inputs):
                ref_inputs = [self._inputs_struct]
            if isinstance(ref_inputs, dict):
                # In the case that the graph is constructed with dict input
                # tensors, We will use the original dict key to map with the
                # keys in the input data. Note that the model.inputs is using
                # tree.flatten to process the input tensors, which means the
                # dict input tensors are ordered by their keys.
                ref_input_names = sorted(ref_inputs.keys())
            else:
                ref_input_names = [
                    inp._keras_history.operation.name for inp in ref_inputs
                ]
            # Raise an warning if there are more input data comparing to input
            # tensor
            if not allow_extra_keys and len(inputs) > len(ref_input_names):
                warnings.warn(
                    "Input dict contained keys {} which did not match any "
                    "model input. They will be ignored by the model.".format(
                        [n for n in inputs.keys() if n not in ref_input_names]
                    ),
                    stacklevel=2,
                )
            # Flatten in the order `Input`s were passed during Model
            # construction.
            return [inputs[n] for n in ref_input_names]
        # Otherwise both ref inputs and inputs will already be in same order.
        return tree.flatten(inputs)

    def _convert_inputs_to_tensors(self, flat_inputs):
        converted = []
        for x, input in zip(flat_inputs, self._inputs):
            converted.append(
                ops.convert_to_tensor(x, dtype=input.dtype, sparse=input.sparse)
            )
        return converted

    def _adjust_input_rank(self, flat_inputs):
        flat_ref_shapes = [x.shape for x in self._inputs]
        adjusted = []
        for x, ref_shape in zip(flat_inputs, flat_ref_shapes):
            x_rank = len(x.shape)
            ref_rank = len(ref_shape)
            if x_rank == ref_rank:
                adjusted.append(x)
                continue
            if x_rank == ref_rank + 1:
                if x.shape[-1] == 1:
                    adjusted.append(ops.squeeze(x, axis=-1))
                    continue
            if x_rank == ref_rank - 1:
                if ref_shape[-1] == 1:
                    adjusted.append(ops.expand_dims(x, axis=-1))
                    continue
            raise ValueError(
                f"Invalid input shape for input {x}. Expected shape "
                f"{ref_shape}, but input has incompatible shape {x.shape}"
            )
        # Add back metadata.
        for i in range(len(flat_inputs)):
            if hasattr(flat_inputs[i], "_keras_history"):
                adjusted[i]._keras_history = flat_inputs[i]._keras_history
            if hasattr(flat_inputs[i], "_keras_mask"):
                adjusted[i]._keras_mask = flat_inputs[i]._keras_mask
        return adjusted

    def _standardize_inputs(self, inputs):
        flat_inputs = self._flatten_to_reference_inputs(inputs)
        flat_inputs = self._convert_inputs_to_tensors(flat_inputs)
        return self._adjust_input_rank(flat_inputs)

    @property
    def input(self):
        # For backwards compatibility,
        # override `input` to retrieve the used-provided
        # constructor inputs
        return self._inputs_struct

    @property
    def output(self):
        return self._outputs_struct

    def add_loss(self, loss):
        # Symbolic only. TODO
        raise NotImplementedError

    @property
    def input_spec(self):
        if hasattr(self, "_manual_input_spec"):
            return self._manual_input_spec

        def shape_with_no_batch_size(x):
            x = list(x)
            if x:
                x[0] = None
            return tuple(x)

        if isinstance(self._inputs_struct, dict):
            # Case where `_nested_inputs` is a plain dict of Inputs.
            names = sorted(self._inputs_struct.keys())
            return [
                InputSpec(
                    shape=shape_with_no_batch_size(
                        self._inputs_struct[name].shape
                    ),
                    allow_last_axis_squeeze=True,
                    name=name,
                )
                for name in names
            ]
        else:
            # Single input, or list/tuple of inputs.
            # The data may be passed as a dict keyed by input name.
            return [
                InputSpec(
                    shape=shape_with_no_batch_size(x.shape),
                    allow_last_axis_squeeze=True,
                    name=x._keras_history[0].name,
                )
                for x in self._inputs
            ]

    @input_spec.setter
    def input_spec(self, value):
        self._manual_input_spec = value

    def get_config(self):
        if not functional_like_constructor(self.__class__):
            # Subclassed networks are not serializable
            # (unless serialization is implemented by
            # the author of the subclassed network).
            return Model.get_config(self)

        config = {
            "name": self.name,
            "trainable": self.trainable,
        }
        # Build a map from a layer unique name (make_node_key)
        # to the index of the nodes that are saved in the config.
        # Only nodes in network_nodes are saved.
        node_reindexing_map = {}
        for operation in self.operations:
            if issubclass(operation.__class__, Functional):
                # Functional models start with a pre-existing node
                # linking their input to output.
                kept_nodes = 1
            else:
                kept_nodes = 0
            for original_node_index, node in enumerate(
                operation._inbound_nodes
            ):
                node_key = make_node_key(operation, original_node_index)
                if node_key in self._nodes:
                    # i.e. we mark it to be saved
                    node_reindexing_map[node_key] = kept_nodes
                    kept_nodes += 1

        # serialize and save the layers in layer_configs
        layer_configs = []
        for operation in self.operations:  # From the earliest layers on.
            filtered_inbound_nodes = []
            for original_node_index, node in enumerate(
                operation._inbound_nodes
            ):
                node_key = make_node_key(operation, original_node_index)
                if node_key in self._nodes:
                    # The node is relevant to the model:
                    # add to filtered_inbound_nodes.
                    node_data = serialize_node(node, node_reindexing_map)
                    if node_data is not None:
                        filtered_inbound_nodes.append(node_data)

            serialize_obj_fn = serialization_lib.serialize_keras_object
            if global_state.get_global_attribute("use_legacy_config", False):
                # Legacy format serialization used for H5 and SavedModel
                serialize_obj_fn = legacy_serialization.serialize_keras_object
            layer_config = serialize_obj_fn(operation)
            layer_config["name"] = operation.name
            layer_config["inbound_nodes"] = filtered_inbound_nodes
            layer_configs.append(layer_config)
        config["layers"] = layer_configs

        # Gather info about inputs and outputs.
        def get_tensor_config(tensor):
            operation = tensor._keras_history[0]
            node_index = tensor._keras_history[1]
            tensor_index = tensor._keras_history[2]
            node_key = make_node_key(operation, node_index)
            assert node_key in self._nodes
            new_node_index = node_reindexing_map[node_key]
            return [operation.name, new_node_index, tensor_index]

        def map_tensors(tensors):
            if isinstance(tensors, dict):
                return {k: get_tensor_config(v) for k, v in tensors.items()}
            if isinstance(tensors, (list, tuple)):
                return [get_tensor_config(v) for v in tensors]
            else:
                return [get_tensor_config(tensors)]

        config["input_layers"] = map_tensors(self._inputs_struct)
        config["output_layers"] = map_tensors(self._outputs_struct)
        return copy.deepcopy(config)


def functional_from_config(cls, config, custom_objects=None):
    """Instantiates a Functional model from its config (from `get_config()`).

    Args:
        cls: Class of the model, e.g. a custom subclass of `Model`.
        config: Output of `get_config()` for the original model instance.
        custom_objects: Optional dict of custom objects.

    Returns:
        An instance of `cls`.
    """
    # Layer instances created during
    # the graph reconstruction process
    created_layers = {}

    # Dictionary mapping layer instances to
    # node data that specifies a layer call.
    # It acts as a queue that maintains any unprocessed
    # layer call until it becomes possible to process it
    # (i.e. until the input tensors to the call all exist).
    unprocessed_nodes = {}

    def add_unprocessed_node(layer, node_data):
        """Add node to layer list

        Arg:
            layer: layer object
            node_data: Node data specifying layer call
        """
        if layer not in unprocessed_nodes:
            unprocessed_nodes[layer] = [node_data]
        else:
            unprocessed_nodes[layer].append(node_data)

    def process_node(layer, node_data):
        """Reconstruct node by linking to inbound layers

        Args:
            layer: Layer to process
            node_data: List of layer configs
        """
        args, kwargs = deserialize_node(node_data, created_layers)
        # Call layer on its inputs, thus creating the node
        # and building the layer if needed.
        layer(*args, **kwargs)

    def process_layer(layer_data):
        """Deserializes a layer, then call it on appropriate inputs.

        Args:
            layer_data: layer config dict.
        """
        layer_name = layer_data["name"]

        # Instantiate layer.
        if "module" not in layer_data:
            # Legacy format deserialization (no "module" key)
            # used for H5 and SavedModel formats
            layer = saving_utils.model_from_config(
                layer_data, custom_objects=custom_objects
            )
        else:
            layer = serialization_lib.deserialize_keras_object(
                layer_data, custom_objects=custom_objects
            )
        created_layers[layer_name] = layer

        # Gather layer inputs.
        inbound_nodes_data = layer_data["inbound_nodes"]
        for node_data in inbound_nodes_data:
            # We don't process nodes (i.e. make layer calls)
            # on the fly because the inbound node may not yet exist,
            # in case of layer shared at different topological depths
            # (e.g. a model such as A(B(A(B(x)))))
            add_unprocessed_node(layer, node_data)

    # First, we create all layers and enqueue nodes to be processed
    for layer_data in config["layers"]:
        process_layer(layer_data)

    # Then we process nodes in order of layer depth.
    # Nodes that cannot yet be processed (if the inbound node
    # does not yet exist) are re-enqueued, and the process
    # is repeated until all nodes are processed.
    while unprocessed_nodes:
        for layer_data in config["layers"]:
            layer = created_layers[layer_data["name"]]

            # Process all nodes in layer, if not yet processed
            if layer in unprocessed_nodes:
                node_data_list = unprocessed_nodes[layer]

                # Process nodes in order
                node_index = 0
                while node_index < len(node_data_list):
                    node_data = node_data_list[node_index]
                    try:
                        process_node(layer, node_data)

                    # If the node does not have all inbound layers
                    # available, stop processing and continue later
                    except IndexError:
                        break

                    node_index += 1

                # If not all nodes processed then store unprocessed nodes
                if node_index < len(node_data_list):
                    unprocessed_nodes[layer] = node_data_list[node_index:]
                # If all nodes processed remove the layer
                else:
                    del unprocessed_nodes[layer]

    # Create lits of input and output tensors and return new class
    name = config.get("name")
    trainable = config.get("trainable")

    def get_tensor(layer_name, node_index, tensor_index):
        assert layer_name in created_layers
        layer = created_layers[layer_name]
        layer_output_tensors = layer._inbound_nodes[node_index].output_tensors
        return layer_output_tensors[tensor_index]

    def map_tensors(tensors):
        if isinstance(tensors, dict):
            return {k: get_tensor(*v) for k, v in tensors.items()}
        else:
            return [get_tensor(*v) for v in tensors]

    input_tensors = map_tensors(config["input_layers"])
    output_tensors = map_tensors(config["output_layers"])
    return cls(
        inputs=input_tensors,
        outputs=output_tensors,
        name=name,
        trainable=trainable,
    )


def operation_fn(operation, training):
    def call(*args, **kwargs):
        if (
            hasattr(operation, "_call_has_training_arg")
            and operation._call_has_training_arg
            and training is not None
        ):
            kwargs["training"] = training
        return operation(*args, **kwargs)

    return call


def functional_like_constructor(cls):
    init_args = inspect.getfullargspec(cls.__init__).args[1:]
    functional_init_args = inspect.getfullargspec(Functional.__init__).args[1:]
    if init_args == functional_init_args:
        return True
    return False


def unpack_singleton(x):
    if isinstance(x, (list, tuple)) and len(x) == 1:
        return x[0]
    return x


def serialize_node(node, node_reindexing_map):
    if not node.input_tensors:
        # Does not need to be serialized.
        return

    args = node.arguments.args
    kwargs = node.arguments.kwargs
    return {
        "args": serialization_lib.serialize_keras_object(args),
        "kwargs": serialization_lib.serialize_keras_object(kwargs),
    }


def deserialize_node(node_data, created_layers):
    """Return (args, kwargs) for calling the node layer."""
    if not node_data:
        return [], {}

    if isinstance(node_data, list):
        # Legacy case.
        input_tensors = []
        for input_data in node_data:
            inbound_layer_name = input_data[0]
            inbound_node_index = input_data[1]
            inbound_tensor_index = input_data[2]
            if len(input_data) == 3:
                kwargs = {}
            elif len(input_data) == 4:
                kwargs = input_data[3]
            else:
                raise ValueError(
                    "Cannot deserialize the model (invalid config data?)"
                )
            inbound_layer = created_layers[inbound_layer_name]

            # Raise an error if the corresponding layer node
            # has not yet been created
            if len(inbound_layer._inbound_nodes) <= inbound_node_index:
                raise IndexError(
                    "Layer node index out of bounds.\n"
                    f"inbound_layer = {inbound_layer}\n"
                    "inbound_layer._inbound_nodes = "
                    f"{inbound_layer._inbound_nodes}\n"
                    f"inbound_node_index = {inbound_node_index}"
                )
            inbound_node = inbound_layer._inbound_nodes[inbound_node_index]
            input_tensors.append(
                inbound_node.output_tensors[inbound_tensor_index]
            )
        return [unpack_singleton(input_tensors)], kwargs

    args = serialization_lib.deserialize_keras_object(node_data["args"])
    kwargs = serialization_lib.deserialize_keras_object(node_data["kwargs"])

    def convert_revived_tensor(x):
        if isinstance(x, backend.KerasTensor):
            history = x._pre_serialization_keras_history
            if history is None:
                return x
            layer = created_layers.get(history[0], None)
            if layer is None:
                raise ValueError(f"Unknown layer: {history[0]}")
            inbound_node_index = history[1]
            inbound_tensor_index = history[2]
            if len(layer._inbound_nodes) <= inbound_node_index:
                raise ValueError(
                    "Layer node index out of bounds.\n"
                    f"inbound_layer = {layer}\n"
                    f"inbound_layer._inbound_nodes = {layer._inbound_nodes}\n"
                    f"inbound_node_index = {inbound_node_index}"
                )
            inbound_node = layer._inbound_nodes[inbound_node_index]
            return inbound_node.output_tensors[inbound_tensor_index]
        return x

    args = tree.map_structure(convert_revived_tensor, args)
    kwargs = tree.map_structure(convert_revived_tensor, kwargs)
    return args, kwargs


def is_input_keras_tensor(x):
    (
        operation,
        node_index,
        _,
    ) = x._keras_history
    node = operation._inbound_nodes[node_index]
    return node.is_input


def clone_single_keras_tensor(x):
    return backend.KerasTensor(
        shape=x.shape, dtype=x.dtype, sparse=x.sparse, name=x.name + "_clone"
    )


def clone_keras_tensors(tensors, kt_id_mapping):
    def swap(x):
        if not isinstance(x, backend.KerasTensor):
            return x
        if id(x) in kt_id_mapping:
            return kt_id_mapping[id(x)]
        new_x = clone_single_keras_tensor(x)
        kt_id_mapping[id(x)] = new_x
        return new_x

    return tree.map_structure(swap, tensors)


def find_nodes_by_inputs_and_outputs(inputs, outputs):
    nodes, _ = _build_map(inputs, outputs)
    return nodes


def clone_graph_nodes(inputs, outputs):
    """Clone the `Node` between the inputs and output tensors.

    This function is used to create a new functional model from any intermediate
    Keras tensors. The clone of the nodes mimic the behavior of reconstructing
    the functional graph network by re-executing all the `__call__()` methods.
    The cloned nodes will be appended to the layers.

    Note that a new `keras.Input` will be created for any items in the
    `inputs`

    Args:
    inputs: A nested structure of `KerasTensor` instances.
    outputs: A nested structure of `KerasTensor` instances.

    Returns:
        A pair of inputs and outputs, with cloned `KerasTensor` instances.
        They can be used to create a new functional model.
    """
    nodes_to_clone = find_nodes_by_inputs_and_outputs(inputs, outputs)
    cloned_inputs = []
    cloned_outputs = []
    # We not only need to create copies of Nodes (mimic the calls), also need to
    # clone Keras tensors to avoid the override of _keras_history attached on
    # the Keras tensor. The following dict is used to track any keras tensor we
    # cloned The key is the string ID of the original keras tensor, and value is
    # the cloned Keras tensor instance.
    kt_id_mapping = {}
    op_id_mapping = {}

    for kt_input in tree.flatten(inputs):
        if is_input_keras_tensor(kt_input):
            # For any existing Keras tensor from keras.Input, leave them as is.
            cloned_inputs.append(kt_input)
            kt_id_mapping[id(kt_input)] = kt_input
        else:
            # We need to create a new Keras tensor for any intermediate tensor
            cloned_input = Input(
                batch_shape=kt_input.shape,
                dtype=kt_input.dtype,
                sparse=kt_input.sparse,
                name=kt_input.name + "CLONE",
            )
            cloned_inputs.append(cloned_input)
            kt_id_mapping[id(kt_input)] = cloned_input
            op_id_mapping[id(kt_input._keras_history[0])] = (
                cloned_input._keras_history[0]
            )
    cloned_inputs = pack_sequence_as(inputs, cloned_inputs)

    for kt_output in tree.flatten(outputs):
        cpy = clone_single_keras_tensor(kt_output)
        # We reuse the _keras_history here, which contains the old information.
        cpy._keras_history = kt_output._keras_history
        cloned_outputs.append(cpy)
        kt_id_mapping[id(kt_output)] = cpy
    cloned_outputs = pack_sequence_as(outputs, cloned_outputs)

    for node in nodes_to_clone:
        if id(node.operation) in op_id_mapping:
            operation = op_id_mapping[id(node.operation)]
        else:
            operation = node.operation
        # Clone any Keras tensor to avoid override of _keras_history
        # Or reuse an existing Keras tensor if it has already been cloned.
        output_copy = clone_keras_tensors(node.output_tensors, kt_id_mapping)
        if not isinstance(operation, InputLayer):
            call_args_copy = clone_keras_tensors(
                node.arguments.args, kt_id_mapping
            )
            call_kwargs_copy = clone_keras_tensors(
                node.arguments.kwargs, kt_id_mapping
            )
        else:
            call_args_copy = ()
            call_kwargs_copy = {}
        # Creating new nodes based on the existing node information.  Node wires
        # itself to inbound and outbound layers.  The Node constructor actually
        # updates this layer's self._inbound_nodes, sets _keras_history on the
        # outputs, and adds itself to the `_outbound_nodes` of the layers that
        # produced the inputs to this layer call.
        Node(
            operation,
            call_args=call_args_copy,
            call_kwargs=call_kwargs_copy,
            outputs=output_copy,
        )
    return cloned_inputs, cloned_outputs


def _check_output_activation_softmax(output_layers):
    """Ensures output activation is suitable.

    Verifies the output layer's activation function is softmax and confirms that
    the axis of application leads to a singular unit output.

    Parameters:
        output_layers: A mapping of output layer names to their respective layer
            instances.
    Raises:
        ValueError: Triggered when the softmax activation results in a constant
            model output of 1.0 across all inputs.
    """

    # remove all the layers except Dense, and BaseConv
    output_layers = {
        k: v
        for k, v in output_layers.items()
        if isinstance(v, (Dense, BaseConv))
    }

    for layer_name, layer in output_layers.items():

        # If the activation is a layer, we can check the axis, but as a
        # precaution, we check if the layer has an axis attribute.
        if hasattr(layer, "activation"):

            act_signature = str(inspect.signature(layer.activation))

            if isinstance(layer.activation, Softmax):
                try:
                    softmax_axis = layer.activation.axis
                except AttributeError:
                    continue

            # This is the case for when user uses "softmax" or keras.ops.softmax
            elif "axis=-1" in act_signature or "axis=None" in act_signature:
                softmax_axis = -1

            # If above conditions are not met, we cannot check the output.
            else:
                continue

            layer_output_shape = layer.output.shape

            if layer_output_shape[softmax_axis] == 1:
                raise ValueError(
                    f"Output layer {layer_name} has a single unit output, "
                    "but the activation is softmax. This is most likely an "
                    "error because softmax outputs sum to 1 therefore single "
                    "unit outputs with softmax will only output 1.0. If you "
                    "think that the error is raised due to an incorrect check, "
                    "please file an issue on "
                    "https://github.com/keras-team/keras/issues. You can "
                    "disable this check by setting "
                    "`validate_output_activation=False` when constructing the "
                    "model."
                )
