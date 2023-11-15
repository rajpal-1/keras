from keras import backend
from keras import ops
from keras.api_export import keras_export
from keras.layers.input_spec import InputSpec
from keras.layers.regularization.dropout import Dropout


class BaseSpatialDropout(Dropout):
    def __init__(self, rate, seed=None, name=None, dtype=None):
        super().__init__(rate, seed=seed, name=name, dtype=dtype)

    def call(self, inputs, training=False):
        if training and self.rate > 0:
            return backend.random.dropout(
                inputs,
                self.rate,
                noise_shape=self._get_noise_shape(inputs),
                seed=self.seed_generator,
            )
        return inputs

    def get_config(self):
        return {
            "rate": self.rate,
            "seed": self.seed,
            "name": self.name,
            "dtype": self.dtype,
        }


@keras_export("keras.layers.SpatialDropout1D")
class SpatialDropout1D(BaseSpatialDropout):
    """Spatial 1D version of Dropout.

    This layer performs the same function as Dropout, however, it drops
    entire 1D feature maps instead of individual elements. If adjacent frames
    within feature maps are strongly correlated (as is normally the case in
    early convolution layers) then regular dropout will not regularize the
    activations and will otherwise just result in an effective learning rate
    decrease. In this case, `SpatialDropout1D` will help promote independence
    between feature maps and should be used instead.

    Args:
        rate: Float between 0 and 1. Fraction of the input units to drop.

    Call arguments:
        inputs: A 3D tensor.
        training: Python boolean indicating whether the layer
            should behave in training mode (applying dropout)
            or in inference mode (pass-through).

    Input shape:
        3D tensor with shape: `(samples, timesteps, channels)`

    Output shape: Same as input.

    Reference:

    - [Tompson et al., 2014](https://arxiv.org/abs/1411.4280)
    """

    def __init__(self, rate, seed=None, name=None, dtype=None):
        super().__init__(rate, seed=seed, name=name, dtype=dtype)
        self.input_spec = InputSpec(ndim=3)

    def _get_noise_shape(self, inputs):
        input_shape = ops.shape(inputs)
        return (input_shape[0], 1, input_shape[2])


@keras_export("keras.layers.SpatialDropout2D")
class SpatialDropout2D(BaseSpatialDropout):
    """Spatial 2D version of Dropout.

    This version performs the same function as Dropout, however, it drops
    entire 2D feature maps instead of individual elements. If adjacent pixels
    within feature maps are strongly correlated (as is normally the case in
    early convolution layers) then regular dropout will not regularize the
    activations and will otherwise just result in an effective learning rate
    decrease. In this case, `SpatialDropout2D` will help promote independence
    between feature maps and should be used instead.

    Args:
        rate: Float between 0 and 1. Fraction of the input units to drop.
        data_format: ```Optional[Literal["channels_last", "channels_first"]]```.
            The ordering of the dimensions in the inputs.
            - `"channels_last"`: input shape `(batch, time, ..., channels)`
            - `"channels_first"`: input shape `(batch, time, channels, ...)`.
            When unspecified, uses `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json` (if exists) else
            `"channels_last"`.

    Call arguments:
        inputs: A 4D tensor.
        training: Python boolean indicating whether the layer
            should behave in training mode (applying dropout)
            or in inference mode (pass-through).

    Input shape:
        4D tensor with shape: `(samples, channels, rows, cols)` if
            data_format='channels_first'
        or 4D tensor with shape: `(samples, rows, cols, channels)` if
            data_format='channels_last'.

    Output shape: Same as input.

    Reference:

    - [Tompson et al., 2014](https://arxiv.org/abs/1411.4280)
    """

    def __init__(
        self, rate, data_format=None, seed=None, name=None, dtype=None
    ):
        super().__init__(rate, seed=seed, name=name, dtype=dtype)
        self.data_format = backend.standardize_data_format(data_format)
        self.input_spec = InputSpec(ndim=4)

    def _get_noise_shape(self, inputs):
        input_shape = ops.shape(inputs)
        if self.data_format == "channels_first":
            return (input_shape[0], input_shape[1], 1, 1)
        elif self.data_format == "channels_last":
            return (input_shape[0], 1, 1, input_shape[3])

    def get_config(self):
        base_config = super().get_config()
        config = {
            "data_format": self.data_format,
        }
        return {**base_config, **config}


@keras_export("keras.layers.SpatialDropout3D")
class SpatialDropout3D(BaseSpatialDropout):
    """Spatial 3D version of Dropout.

    This version performs the same function as Dropout, however, it drops
    entire 3D feature maps instead of individual elements. If adjacent voxels
    within feature maps are strongly correlated (as is normally the case in
    early convolution layers) then regular dropout will not regularize the
    activations and will otherwise just result in an effective learning rate
    decrease. In this case, SpatialDropout3D will help promote independence
    between feature maps and should be used instead.

    Args:
        rate: Float between 0 and 1. Fraction of the input units to drop.
        data_format: ```Optional[Literal["channels_last", "channels_first"]]```.
            The ordering of the dimensions in the inputs.
            - `"channels_last"`: input shape `(batch, time, ..., channels)`
            - `"channels_first"`: input shape `(batch, time, channels, ...)`.
            When unspecified, uses `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json` (if exists) else
            `"channels_last"`.

    Call arguments:
        inputs: A 5D tensor.
        training: Python boolean indicating whether the layer
                should behave in training mode (applying dropout)
                or in inference mode (pass-through).

    Input shape:
        5D tensor with shape: `(samples, channels, dim1, dim2, dim3)` if
            data_format='channels_first'
        or 5D tensor with shape: `(samples, dim1, dim2, dim3, channels)` if
            data_format='channels_last'.

    Output shape: Same as input.

    Reference:

    - [Tompson et al., 2014](https://arxiv.org/abs/1411.4280)
    """

    def __init__(
        self, rate, data_format=None, seed=None, name=None, dtype=None
    ):
        super().__init__(rate, seed=seed, name=name, dtype=dtype)
        self.data_format = backend.standardize_data_format(data_format)
        self.input_spec = InputSpec(ndim=5)

    def _get_noise_shape(self, inputs):
        input_shape = ops.shape(inputs)
        if self.data_format == "channels_first":
            return (input_shape[0], input_shape[1], 1, 1, 1)
        elif self.data_format == "channels_last":
            return (input_shape[0], 1, 1, 1, input_shape[4])

    def get_config(self):
        base_config = super().get_config()
        config = {
            "data_format": self.data_format,
        }
        return {**base_config, **config}
