'''NASNet-A models for Keras.

NASNet refers to Neural Architecture Search Network, a family of models
that were designed automatically by learning the model architectures
directly on the dataset of interest.

Here we consider NASNet-A, the highest performance model that was found
for the CIFAR-10 dataset, and then extended to ImageNet 2012 dataset,
obtaining state of the art performance on CIFAR-10 and ImageNet 2012.
Only the NASNet-A models, and their respective weights, which are suited
for ImageNet 2012 are provided.

The below table describes the performance on ImageNet 2012:
--------------------------------------------------------------------------------
      Architecture       | Top-1 Acc | Top-5 Acc |  Multiply-Adds |  Params (M)
--------------------------------------------------------------------------------
|   NASNet-A (4 @ 1056)  |   74.0 %  |   91.6 %  |       564 M    |     5.3    |
|   NASNet-A (6 @ 4032)  |   82.7 %  |   96.2 %  |      23.8 B    |    88.9    |
--------------------------------------------------------------------------------

Weights obtained from the official TensorFlow repository found at
https://github.com/tensorflow/models/tree/master/research/slim/nets/nasnet

# References
 - [Learning Transferable Architectures for Scalable Image Recognition]
    (https://arxiv.org/abs/1707.07012)

# Based on the following implementations
 - [TF Slim Implementation]
   (https://github.com/tensorflow/models/blob/master/research/slim/nets/nasnet/nasnet.py)
 - [TensorNets implementation]
   (https://github.com/taehoonlee/tensornets/blob/master/tensornets/nasnets.py)
'''
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

import os
import warnings

from ..models import Model
from ..layers import Input
from ..layers import Activation
from ..layers import Dense
from ..layers import BatchNormalization
from ..layers import MaxPooling2D
from ..layers import AveragePooling2D
from ..layers import GlobalAveragePooling2D
from ..layers import GlobalMaxPooling2D
from ..layers import Conv2D
from ..layers import SeparableConv2D
from ..layers import ZeroPadding2D
from ..layers import Cropping2D
from ..layers import concatenate
from ..layers import add
from ..utils.data_utils import get_file
from ..engine.topology import get_source_inputs
from ..applications.imagenet_utils import _obtain_input_shape
from ..applications.inception_v3 import preprocess_input
from ..applications.imagenet_utils import decode_predictions
from .. import backend as K

NASNET_MOBILE_WEIGHT_PATH = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.8/NASNet-mobile.h5'
NASNET_MOBILE_WEIGHT_PATH_NO_TOP = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.8/NASNet-mobile-no-top.h5'
NASNET_LARGE_WEIGHT_PATH = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.8/NASNet-large.h5'
NASNET_LARGE_WEIGHT_PATH_NO_TOP = 'https://github.com/fchollet/deep-learning-models/releases/download/v0.8/NASNet-large-no-top.h5'


def NASNet(input_shape=None,
           penultimate_filters=4032,
           num_blocks=6,
           stem_block_filters=96,
           skip_reduction=True,
           filter_multiplier=2,
           include_top=True,
           weights=None,
           input_tensor=None,
           pooling=None,
           classes=1000,
           default_size=None):
    '''Instantiates a NASNet model.

    Note that only TensorFlow is supported for now,
    therefore it only works with the data format
    `image_data_format='channels_last'` in your Keras config
    at `~/.keras/keras.json`.

    # Arguments
        input_shape: Optional shape tuple, the input shape
            is by default `(331, 331, 3)` for NASNetLarge and
            `(224, 224, 3)` for NASNetMobile.
            It should have exactly 3 inputs channels,
            and width and height should be no smaller than 32.
            E.g. `(224, 224, 3)` would be one valid value.
        penultimate_filters: Number of filters in the penultimate layer.
            NASNet models use the notation `NASNet (N @ P)`, where:
                -   N is the number of blocks
                -   P is the number of penultimate filters
        num_blocks: Number of repeated blocks of the NASNet model.
            NASNet models use the notation `NASNet (N @ P)`, where:
                -   N is the number of blocks
                -   P is the number of penultimate filters
        stem_block_filters: Number of filters in the initial stem block
        skip_reduction: Whether to skip the reduction step at the tail
            end of the network. Set to `False` for CIFAR models.
        filter_multiplier: Controls the width of the network.
            - If `filter_multiplier` < 1.0, proportionally decreases the number
                of filters in each layer.
            - If `filter_multiplier` > 1.0, proportionally increases the number
                of filters in each layer.
            - If `filter_multiplier` = 1, default number of filters from the
                 paper are used at each layer.
        include_top: Whether to include the fully-connected
            layer at the top of the network.
        weights: `None` (random initialization) or
            `imagenet` (ImageNet weights)
        input_tensor: Optional Keras tensor (i.e. output of
            `layers.Input()`)
            to use as image input for the model.
        pooling: Optional pooling mode for feature extraction
            when `include_top` is `False`.
            - `None` means that the output of the model
                will be the 4D tensor output of the
                last convolutional layer.
            - `avg` means that global average pooling
                will be applied to the output of the
                last convolutional layer, and thus
                the output of the model will be a
                2D tensor.
            - `max` means that global max pooling will
                be applied.
        classes: Optional number of classes to classify images
            into, only to be specified if `include_top` is True, and
            if no `weights` argument is specified.
        default_size: Specifies the default image size of the model

    # Returns
        A Keras model instance.

    # Raises
        ValueError: In case of invalid argument for `weights`,
            invalid input shape or invalid `penultimate_filters` value.
        RuntimeError: If attempting to run this model with a
            backend that does not support separable convolutions.
    '''
    if K.backend() != 'tensorflow':
        raise RuntimeError('Only TensorFlow backend is currently supported, '
                           'as other backends do not support '
                           'separable convolution.')

    if not (weights in {'imagenet', None} or os.path.exists(weights)):
        raise ValueError('The `weights` argument should be either '
                         '`None` (random initialization), `imagenet` '
                         '(pre-training on ImageNet), '
                         'or the path to the weights file to be loaded.')

    if weights == 'imagenet' and include_top and classes != 1000:
        raise ValueError('If using `weights` as ImageNet with `include_top` '
                         'as true, `classes` should be 1000')

    if (isinstance(input_shape, tuple) and
            None in input_shape and
            weights == 'imagenet'):
        raise ValueError('When specifying the input shape of a NASNet'
                         ' and loading `ImageNet` weights, '
                         'the input_shape argument must be static '
                         '(no None entries). Got: `input_shape='
                         + str(input_shape) + '`.')

    if default_size is None:
        default_size = 331

    # Determine proper input shape and default size.
    input_shape = _obtain_input_shape(input_shape,
                                      default_size=default_size,
                                      min_size=32,
                                      data_format=K.image_data_format(),
                                      require_flatten=False,
                                      weights=weights)

    if K.image_data_format() != 'channels_last':
        warnings.warn('The NASNet family of models is only available '
                      'for the input data format "channels_last" '
                      '(width, height, channels). '
                      'However your settings specify the default '
                      'data format "channels_first" (channels, width, height).'
                      ' You should set `image_data_format="channels_last"` '
                      'in your Keras config located at ~/.keras/keras.json. '
                      'The model being returned right now will expect inputs '
                      'to follow the "channels_last" data format.')
        K.set_image_data_format('channels_last')
        old_data_format = 'channels_first'
    else:
        old_data_format = None

    if input_tensor is None:
        img_input = Input(shape=input_shape)
    else:
        if not K.is_keras_tensor(input_tensor):
            img_input = Input(tensor=input_tensor, shape=input_shape)
        else:
            img_input = input_tensor

    if penultimate_filters % 24 != 0:
        raise ValueError(
            'For NASNet-A models, the value of `penultimate_filters` '
            'needs to be divisible by 24. Current value: %d' %
            penultimate_filters)

    channel_dim = 1 if K.image_data_format() == 'channels_first' else -1
    filters = penultimate_filters // 24

    if not skip_reduction:
        x = Conv2D(stem_block_filters, (3, 3), strides=(2, 2), padding='valid',
                   use_bias=False, name='stem_conv1',
                   kernel_initializer='he_normal')(img_input)
    else:
        x = Conv2D(stem_block_filters, (3, 3), strides=(1, 1), padding='same',
                   use_bias=False, name='stem_conv1',
                   kernel_initializer='he_normal')(img_input)

    x = BatchNormalization(axis=channel_dim, momentum=0.9997,
                           epsilon=1e-3, name='stem_bn1')(x)

    p = None
    if not skip_reduction:  # imagenet / mobile mode
        x, p = _reduction_a_cell(x, p, filters // (filter_multiplier ** 2),
                                 block_id='stem_1')
        x, p = _reduction_a_cell(x, p, filters // filter_multiplier,
                                 block_id='stem_2')

    for i in range(num_blocks):
        x, p = _normal_a_cell(x, p, filters, block_id='%d' % (i))

    x, p0 = _reduction_a_cell(x, p, filters * filter_multiplier,
                              block_id='reduce_%d' % (num_blocks))

    p = p0 if not skip_reduction else p

    for i in range(num_blocks):
        x, p = _normal_a_cell(x, p, filters * filter_multiplier,
                              block_id='%d' % (num_blocks + i + 1))

    x, p0 = _reduction_a_cell(x, p, filters * filter_multiplier ** 2,
                              block_id='reduce_%d' % (2 * num_blocks))

    p = p0 if not skip_reduction else p

    for i in range(num_blocks):
        x, p = _normal_a_cell(x, p, filters * filter_multiplier ** 2,
                              block_id='%d' % (2 * num_blocks + i + 1))

    x = Activation('relu')(x)

    if include_top:
        x = GlobalAveragePooling2D()(x)
        x = Dense(classes, activation='softmax', name='predictions')(x)
    else:
        if pooling == 'avg':
            x = GlobalAveragePooling2D()(x)
        elif pooling == 'max':
            x = GlobalMaxPooling2D()(x)

    # Ensure that the model takes into account
    # any potential predecessors of `input_tensor`.
    if input_tensor is not None:
        inputs = get_source_inputs(input_tensor)
    else:
        inputs = img_input

    model = Model(inputs, x, name='NASNet')

    # load weights
    if weights == 'imagenet':
        if default_size == 224:  # mobile version
            if include_top:
                weight_path = NASNET_MOBILE_WEIGHT_PATH
                model_name = 'nasnet_mobile.h5'
            else:
                weight_path = NASNET_MOBILE_WEIGHT_PATH_NO_TOP
                model_name = 'nasnet_mobile_no_top.h5'

            weights_file = get_file(model_name, weight_path,
                                    cache_subdir='models')
            model.load_weights(weights_file)

        elif default_size == 331:  # large version
            if include_top:
                weight_path = NASNET_LARGE_WEIGHT_PATH
                model_name = 'nasnet_large.h5'
            else:
                weight_path = NASNET_LARGE_WEIGHT_PATH_NO_TOP
                model_name = 'nasnet_large_no_top.h5'

            weights_file = get_file(model_name, weight_path,
                                    cache_subdir='models')
            model.load_weights(weights_file)
        else:
            raise ValueError(
                'ImageNet weights can only be loaded with NASNetLarge'
                ' or NASNetMobile')
    elif weights is not None:
        model.load_weights(weights)

    if old_data_format:
        K.set_image_data_format(old_data_format)

    return model


def NASNetLarge(input_shape=None,
                include_top=True,
                weights='imagenet',
                input_tensor=None,
                pooling=None,
                classes=1000):
    '''Instantiates a NASNet model in ImageNet mode.

    Note that only TensorFlow is supported for now,
    therefore it only works with the data format
    `image_data_format='channels_last'` in your Keras config
    at `~/.keras/keras.json`.

    # Arguments
        input_shape: Optional shape tuple, only to be specified
            if `include_top` is False (otherwise the input shape
            has to be `(331, 331, 3)` for NASNetLarge.
            It should have exactly 3 inputs channels,
            and width and height should be no smaller than 32.
            E.g. `(224, 224, 3)` would be one valid value.
        include_top: Whether to include the fully-connected
            layer at the top of the network.
        weights: `None` (random initialization) or
            `imagenet` (ImageNet weights)
        input_tensor: Optional Keras tensor (i.e. output of
            `layers.Input()`)
            to use as image input for the model.
        pooling: Optional pooling mode for feature extraction
            when `include_top` is `False`.
            - `None` means that the output of the model
                will be the 4D tensor output of the
                last convolutional layer.
            - `avg` means that global average pooling
                will be applied to the output of the
                last convolutional layer, and thus
                the output of the model will be a
                2D tensor.
            - `max` means that global max pooling will
                be applied.
        classes: Optional number of classes to classify images
            into, only to be specified if `include_top` is True, and
            if no `weights` argument is specified.

    # Returns
        A Keras model instance.

    # Raises
        ValueError: in case of invalid argument for `weights`,
            or invalid input shape.
        RuntimeError: If attempting to run this model with a
            backend that does not support separable convolutions.
    '''
    return NASNet(input_shape,
                  penultimate_filters=4032,
                  num_blocks=6,
                  stem_block_filters=96,
                  skip_reduction=False,
                  filter_multiplier=2,
                  include_top=include_top,
                  weights=weights,
                  input_tensor=input_tensor,
                  pooling=pooling,
                  classes=classes,
                  default_size=331)


def NASNetMobile(input_shape=None,
                 include_top=True,
                 weights='imagenet',
                 input_tensor=None,
                 pooling=None,
                 classes=1000):
    '''Instantiates a Mobile NASNet model in ImageNet mode.

    Note that only TensorFlow is supported for now,
    therefore it only works with the data format
    `image_data_format='channels_last'` in your Keras config
    at `~/.keras/keras.json`.

    # Arguments
        input_shape: Optional shape tuple, only to be specified
            if `include_top` is False (otherwise the input shape
            has to be `(224, 224, 3)` for NASNetMobile
            It should have exactly 3 inputs channels,
            and width and height should be no smaller than 32.
            E.g. `(224, 224, 3)` would be one valid value.
        include_top: Whether to include the fully-connected
            layer at the top of the network.
        weights: `None` (random initialization) or
            `imagenet` (ImageNet weights)
        input_tensor: Optional Keras tensor (i.e. output of
            `layers.Input()`)
            to use as image input for the model.
        pooling: Optional pooling mode for feature extraction
            when `include_top` is `False`.
            - `None` means that the output of the model
                will be the 4D tensor output of the
                last convolutional layer.
            - `avg` means that global average pooling
                will be applied to the output of the
                last convolutional layer, and thus
                the output of the model will be a
                2D tensor.
            - `max` means that global max pooling will
                be applied.
        classes: Optional number of classes to classify images
            into, only to be specified if `include_top` is True, and
            if no `weights` argument is specified.

    # Returns
        A Keras model instance.

    # Raises
        ValueError: In case of invalid argument for `weights`,
            or invalid input shape.
        RuntimeError: If attempting to run this model with a
            backend that does not support separable convolutions.
    '''
    return NASNet(input_shape,
                  penultimate_filters=1056,
                  num_blocks=4,
                  stem_block_filters=32,
                  skip_reduction=False,
                  filter_multiplier=2,
                  include_top=include_top,
                  weights=weights,
                  input_tensor=input_tensor,
                  pooling=pooling,
                  classes=classes,
                  default_size=224)


def _separable_conv_block(ip, filters,
                          kernel_size=(3, 3),
                          strides=(1, 1),
                          block_id=None):
    '''Adds 2 blocks of [relu-separable conv-batchnorm].

    # Arguments
        ip: Input tensor
        filters: Number of output filters per layer
        kernel_size: Kernel size of separable convolutions
        strides: Strided convolution for downsampling
        block_id: String block_id

    # Returns
        A Keras tensor
    '''
    channel_dim = 1 if K.image_data_format() == 'channels_first' else -1

    with K.name_scope('separable_conv_block_%s' % block_id):
        x = Activation('relu')(ip)
        x = SeparableConv2D(filters, kernel_size, strides=strides,
                            name='separable_conv_1_%s' % block_id,
                            padding='same', use_bias=False,
                            kernel_initializer='he_normal')(x)
        x = BatchNormalization(axis=channel_dim, momentum=0.9997,
                               epsilon=1e-3,
                               name='separable_conv_1_bn_%s' % (block_id))(x)
        x = Activation('relu')(x)
        x = SeparableConv2D(filters, kernel_size,
                            name='separable_conv_2_%s' % block_id,
                            padding='same', use_bias=False,
                            kernel_initializer='he_normal')(x)
        x = BatchNormalization(axis=channel_dim, momentum=0.9997,
                               epsilon=1e-3,
                               name='separable_conv_2_bn_%s' % (block_id))(x)
    return x


def _adjust_block(p, ip, filters, block_id=None):
    '''Adjusts the input `previous path` to match the shape of the `input`.

    Used in situations where the output number of filters needs to be changed.

    # Arguments
        p: Input tensor which needs to be modified
        ip: Input tensor whose shape needs to be matched
        filters: Number of output filters to be matched
        block_id: String block_id

    # Returns
        Adjusted Keras tensor
    '''
    channel_dim = 1 if K.image_data_format() == 'channels_first' else -1
    img_dim = 2 if K.image_data_format() == 'channels_first' else -2

    ip_shape = K.int_shape(ip)

    if p is not None:
        p_shape = K.int_shape(p)

    with K.name_scope('adjust_block'):
        if p is None:
            p = ip

        elif p_shape[img_dim] != ip_shape[img_dim]:
            with K.name_scope('adjust_reduction_block_%s' % block_id):
                p = Activation('relu', name='adjust_relu_1_%s' % block_id)(p)

                p1 = AveragePooling2D((1, 1), strides=(2, 2), padding='valid',
                                      name='adjust_avg_pool_1_%s' % block_id)(p)
                p1 = Conv2D(filters // 2, (1, 1), padding='same',
                            use_bias=False, name='adjust_conv_1_%s' % block_id,
                            kernel_initializer='he_normal')(p1)

                p2 = ZeroPadding2D(padding=((0, 1), (0, 1)))(p)
                p2 = Cropping2D(cropping=((1, 0), (1, 0)))(p2)
                p2 = AveragePooling2D((1, 1), strides=(2, 2), padding='valid',
                                      name='adjust_avg_pool_2_%s' % block_id)(
                    p2)
                p2 = Conv2D(filters // 2, (1, 1), padding='same',
                            use_bias=False, name='adjust_conv_2_%s' % block_id,
                            kernel_initializer='he_normal')(p2)

                p = concatenate([p1, p2], axis=channel_dim)
                p = BatchNormalization(axis=channel_dim, momentum=0.9997,
                                       epsilon=1e-3,
                                       name='adjust_bn_%s' % block_id)(p)

        elif p_shape[channel_dim] != filters:
            with K.name_scope('adjust_projection_block_%s' % block_id):
                p = Activation('relu')(p)
                p = Conv2D(filters, (1, 1), strides=(1, 1), padding='same',
                           name='adjust_conv_projection_%s' % block_id,
                           use_bias=False, kernel_initializer='he_normal')(p)
                p = BatchNormalization(axis=channel_dim, momentum=0.9997,
                                       epsilon=1e-3,
                                       name='adjust_bn_%s' % block_id)(p)
    return p


def _normal_a_cell(ip, p, filters, block_id=None):
    '''Adds a Normal cell for NASNet-A (Fig. 4 in the paper).

    # Arguments
        ip: Input tensor `x`
        p: Input tensor `p`
        filters: Number of output filters
        block_id: String block_id

    # Returns
        A Keras tensor
    '''
    channel_dim = 1 if K.image_data_format() == 'channels_first' else -1

    with K.name_scope('normal_A_block_%s' % block_id):
        p = _adjust_block(p, ip, filters, block_id)

        h = Activation('relu')(ip)
        h = Conv2D(filters, (1, 1), strides=(1, 1), padding='same',
                   name='normal_conv_1_%s' % block_id,
                   use_bias=False, kernel_initializer='he_normal')(h)
        h = BatchNormalization(axis=channel_dim, momentum=0.9997,
                               epsilon=1e-3,
                               name='normal_bn_1_%s' % block_id)(h)

        with K.name_scope('block_1'):
            x1_1 = _separable_conv_block(h, filters, kernel_size=(5, 5),
                                         block_id='normal_left1_%s' % block_id)
            x1_2 = _separable_conv_block(p, filters,
                                         block_id='normal_right1_%s' % block_id)
            x1 = add([x1_1, x1_2], name='normal_add_1_%s' % block_id)

        with K.name_scope('block_2'):
            x2_1 = _separable_conv_block(p, filters, (5, 5),
                                         block_id='normal_left2_%s' % block_id)
            x2_2 = _separable_conv_block(p, filters, (3, 3),
                                         block_id='normal_right2_%s' % block_id)
            x2 = add([x2_1, x2_2], name='normal_add_2_%s' % block_id)

        with K.name_scope('block_3'):
            x3 = AveragePooling2D((3, 3), strides=(1, 1), padding='same',
                                  name='normal_left3_%s' % (block_id))(h)
            x3 = add([x3, p], name='normal_add_3_%s' % block_id)

        with K.name_scope('block_4'):
            x4_1 = AveragePooling2D((3, 3), strides=(1, 1), padding='same',
                                    name='normal_left4_%s' % (block_id))(p)
            x4_2 = AveragePooling2D((3, 3), strides=(1, 1), padding='same',
                                    name='normal_right4_%s' % (block_id))(p)
            x4 = add([x4_1, x4_2], name='normal_add_4_%s' % block_id)

        with K.name_scope('block_5'):
            x5 = _separable_conv_block(h, filters,
                                       block_id='normal_left5_%s' % block_id)
            x5 = add([x5, h], name='normal_add_5_%s' % block_id)

        x = concatenate([p, x1, x2, x3, x4, x5], axis=channel_dim,
                        name='normal_concat_%s' % block_id)
    return x, ip


def _reduction_a_cell(ip, p, filters, block_id=None):
    '''Adds a Reduction cell for NASNet-A (Fig. 4 in the paper).

    # Arguments
        ip: Input tensor `x`
        p: Input tensor `p`
        filters: Number of output filters
        block_id: String block_id

    # Returns
        A Keras tensor
    '''
    channel_dim = 1 if K.image_data_format() == 'channels_first' else -1

    with K.name_scope('reduction_A_block_%s' % block_id):
        p = _adjust_block(p, ip, filters, block_id)

        h = Activation('relu')(ip)
        h = Conv2D(filters, (1, 1), strides=(1, 1), padding='same',
                   name='reduction_conv_1_%s' % block_id,
                   use_bias=False, kernel_initializer='he_normal')(h)
        h = BatchNormalization(axis=channel_dim, momentum=0.9997,
                               epsilon=1e-3,
                               name='reduction_bn_1_%s' % block_id)(h)

        with K.name_scope('block_1'):
            x1_1 = _separable_conv_block(h, filters, (5, 5), strides=(2, 2),
                                         block_id='reduction_left1_%s' % block_id)
            x1_2 = _separable_conv_block(p, filters, (7, 7), strides=(2, 2),
                                         block_id='reduction_1_%s' % block_id)
            x1 = add([x1_1, x1_2], name='reduction_add_1_%s' % block_id)

        with K.name_scope('block_2'):
            x2_1 = MaxPooling2D((3, 3), strides=(2, 2), padding='same',
                                name='reduction_left2_%s' % block_id)(h)
            x2_2 = _separable_conv_block(p, filters, (7, 7), strides=(2, 2),
                                         block_id='reduction_right2_%s' % block_id)
            x2 = add([x2_1, x2_2], name='reduction_add_2_%s' % block_id)

        with K.name_scope('block_3'):
            x3_1 = AveragePooling2D((3, 3), strides=(2, 2), padding='same',
                                    name='reduction_left3_%s' % block_id)(h)
            x3_2 = _separable_conv_block(p, filters, (5, 5), strides=(2, 2),
                                         block_id='reduction_right3_%s' % block_id)
            x3 = add([x3_1, x3_2], name='reduction_add3_%s' % block_id)

        with K.name_scope('block_4'):
            x4 = AveragePooling2D((3, 3), strides=(1, 1), padding='same',
                                  name='reduction_left4_%s' % block_id)(x1)
            x4 = add([x2, x4])

        with K.name_scope('block_5'):
            x5_1 = _separable_conv_block(x1, filters, (3, 3),
                                         block_id='reduction_left4_%s' % block_id)
            x5_2 = MaxPooling2D((3, 3), strides=(2, 2), padding='same',
                                name='reduction_right5_%s' % block_id)(h)
            x5 = add([x5_1, x5_2], name='reduction_add4_%s' % block_id)

        x = concatenate([x2, x3, x4, x5], axis=channel_dim,
                        name='reduction_concat_%s' % block_id)
        return x, ip
