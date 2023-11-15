from keras import backend
from keras import ops
from keras.api_export import keras_export
from keras.layers.pooling.base_global_pooling import BaseGlobalPooling


@keras_export(
    [
        "keras.layers.GlobalAveragePooling1D",
        "keras.layers.GlobalAvgPool1D",
    ]
)
class GlobalAveragePooling1D(BaseGlobalPooling):
    """Global average pooling operation for temporal data.

    Args:
        data_format: ```Optional[Literal["channels_last", "channels_first"]]```.
            The ordering of the dimensions in the inputs.
            - `"channels_last"`: input shape `(batch, time, ..., channels)`
            - `"channels_first"`: input shape `(batch, time, channels, ...)`.
            When unspecified, uses `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json` (if exists) else
            `"channels_last"`.
        keepdims: A boolean, whether to keep the temporal dimension or not.
            If `keepdims` is `False` (default), the rank of the tensor is
            reduced for spatial dimensions. If `keepdims` is `True`, the
            temporal dimension are retained with length 1.
            The behavior is the same as for `tf.reduce_mean` or `np.mean`.

    Call arguments:
        inputs: A 3D tensor.
        mask: Binary tensor of shape `(batch_size, steps)` indicating whether
            a given step should be masked (excluded from the average).

    Input shape:

    - If `data_format='channels_last'`:
        3D tensor with shape:
        `(batch_size, steps, features)`
    - If `data_format='channels_first'`:
        3D tensor with shape:
        `(batch_size, features, steps)`

    Output shape:

    - If `keepdims=False`:
        2D tensor with shape `(batch_size, features)`.
    - If `keepdims=True`:
        - If `data_format="channels_last"`:
            3D tensor with shape `(batch_size, 1, features)`
        - If `data_format="channels_first"`:
            3D tensor with shape `(batch_size, features, 1)`

    Example:

    >>> x = np.random.rand(2, 3, 4)
    >>> y = keras.layers.GlobalAveragePooling1D()(x)
    >>> y.shape
    (2, 4)
    """

    def __init__(self, data_format=None, keepdims=False, **kwargs):
        super().__init__(
            pool_dimensions=1,
            data_format=data_format,
            keepdims=keepdims,
            **kwargs,
        )
        self.supports_masking = True

    def call(self, inputs, mask=None):
        steps_axis = 1 if self.data_format == "channels_last" else 2
        if mask is not None:
            mask = backend.cast(mask, inputs[0].dtype)
            mask = ops.expand_dims(
                mask, 2 if self.data_format == "channels_last" else 1
            )
            inputs *= mask
            return ops.sum(
                inputs, axis=steps_axis, keepdims=self.keepdims
            ) / ops.sum(mask, axis=steps_axis, keepdims=self.keepdims)
        else:
            return ops.mean(inputs, axis=steps_axis, keepdims=self.keepdims)

    def compute_mask(self, inputs, mask=None):
        return None
