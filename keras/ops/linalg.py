from keras import backend
from keras.api_export import keras_export
from keras.backend import KerasTensor
from keras.backend import any_symbolic_tensors
from keras.ops.operation import Operation


class LinalgError(ValueError):
    """Generic exception raised by linalg operations.

    Raised when a linear algebra-related condition prevents the correct
    execution of the operation.
    """


class Cholesky(Operation):
    def __init__(self):
        super().__init__()

    def call(self, x):
        return _cholesky(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        _assert_square(x)
        return KerasTensor(x.shape, x.dtype)


@keras_export("keras.ops.linalg.cholesky")
def cholesky(x):
    """Computes the Cholesky decomposition of a positive semi-definite matrix.

    Args:
        x: A tensor or variable.

    Returns:
        A tensor.

    """
    if any_symbolic_tensors((x,)):
        return Cholesky().symbolic_call(x)
    return _cholesky(x)


def _cholesky(x):
    _assert_2d(x)
    _assert_square(x)
    try:
        return backend.linalg.cholesky(x)
    except Exception as e:
        raise LinalgError("Cholesky decomposition failed: " + str(e))


class Det(Operation):

    def __init__(self):
        super().__init__()

    def call(self, x):
        return _det(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        _assert_square(x)
        return KerasTensor(x.shape[:-2], x.dtype)


@keras_export("keras.ops.linalg.det")
def det(x):
    """Computes the determinant of a square tensor.

    Args:
        x: Input tensor of shape (..., M, M)

    Returns:
        A tensor of shape (...,) as the determinant of `x`.

    """
    if any_symbolic_tensors((x,)):
        return Det().symbolic_call(x)
    return _det(x)


def _det(x):
    _assert_2d(x)
    _assert_square(x)
    return backend.linalg.det(x)


class Eig(Operation):

    def __init__(self):
        super().__init__()

    def call(self, x):
        return _eig(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        _assert_square(x)
        return (
            KerasTensor(x.shape[:-1], x.dtype),
            KerasTensor(x.shape, x.dtype),
        )


@keras_export("keras.ops.linalg.eig")
def eig(x):
    """Computes the eigenvalues and eigenvectors of a square matrix.

    Args:
        x: A tensor of shape (..., M, M).

    Returns:
        A tuple of two tensors: a tensor of shape (..., M) containing the eigenvalues
        and a tensor of shape (..., M, M) containing the eigenvectors.

    """
    if any_symbolic_tensors((x,)):
        return Eig().symbolic_call(x)
    return _eig(x)


def _eig(x):
    _assert_2d(x)
    _assert_square(x)
    return backend.linalg.eig(x)


class Inv(Operation):

    def __init__(self):
        super().__init__()

    def call(self, x):
        return _inv(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        _assert_square(x)
        return KerasTensor(x.shape, x.dtype)


@keras_export("keras.ops.linalg.inv")
def inv(x):
    """Computes the inverse of a square tensor.

    Args:
        x: Input tensor of shape (..., M, M).

    Returns:
        A tensor of shape (..., M, M) representing the inverse of `x`.

    """
    if any_symbolic_tensors((x,)):
        return Inv().symbolic_call(x)
    return _inv(x)


def _inv(x):
    _assert_2d(x)
    _assert_square(x)
    return backend.linalg.inv(x)


class Lu(Operation):

    def __init__(self):
        super().__init__()

    def call(self, x):
        return _lu(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        _assert_square(x)
        return (
            KerasTensor(x.shape, x.dtype),
            KerasTensor(x.shape, x.dtype),
            KerasTensor(x.shape[:-1], x.dtype),
        )


@keras_export("keras.ops.linalg.lu")
def lu(x):
    """Computes the lower-upper decomposition of a square matrix.

    Args:
        x: A tensor of shape (..., M, M).

    Returns:
        A tuple of three tensors: a tensor of shape (..., M, M) containing the
        lower triangular matrix, a tensor of shape (..., M, M) containing the
        upper triangular matrix and a tensor of shape (..., M) containing the
        permutation indices.

    """
    if any_symbolic_tensors((x,)):
        return Lu().symbolic_call(x)
    return _lu(x)


def _lu(x):
    _assert_2d(x)
    _assert_square(x)
    return backend.linalg.lu(x)


class Norm(Operation):
    def __init__(self, ord=None, axis=None, keepdims=False):
        super().__init__()
        if isinstance(ord, str):
            if ord not in ("fro", "nuc"):
                raise ValueError(
                    "Invalid `ord` argument. "
                    "Expected one of {'fro', 'nuc'} when using string. "
                    f"Received: ord={ord}"
                )
        if isinstance(axis, int):
            axis = [axis]
        self.ord = ord
        self.axis = axis
        self.keepdims = keepdims

    def compute_output_spec(self, x):
        output_dtype = backend.standardize_dtype(x.dtype)
        if "int" in output_dtype or output_dtype == "bool":
            output_dtype = backend.floatx()
        if self.axis is None:
            axis = tuple(range(len(x.shape)))
        else:
            axis = self.axis
        num_axes = len(axis)
        if num_axes == 1 and isinstance(self.ord, str):
            raise ValueError(
                "Invalid `ord` argument for vector norm. "
                f"Received: ord={self.ord}"
            )
        elif num_axes == 2 and self.ord not in (
            None,
            "fro",
            "nuc",
            float("inf"),
            float("-inf"),
            1,
            -1,
            2,
            -2,
        ):
            raise ValueError(
                "Invalid `ord` argument for matrix norm. "
                f"Received: ord={self.ord}"
            )
        return KerasTensor(
            reduce_shape(x.shape, axis=self.axis, keepdims=self.keepdims),
            dtype=output_dtype,
        )

    def call(self, x):
        x = backend.convert_to_tensor(x)
        return backend.linalg.norm(
            x, ord=self.ord, axis=self.axis, keepdims=self.keepdims
        )


@keras_export("keras.ops.linalg.norm")
def norm(x, ord=None, axis=None, keepdims=False):
    """Matrix or vector norm.

    This function is able to return one of eight different matrix norms, or one
    of an infinite number of vector norms (described below), depending on the
    value of the `ord` parameter.

    Args:
        x: Input tensor.
        ord: Order of the norm (see table under Notes). The default is `None`.
        axis: If `axis` is an integer, it specifies the axis of `x` along which
            to compute the vector norms. If `axis` is a 2-tuple, it specifies
            the axes that hold 2-D matrices, and the matrix norms of these
            matrices are computed.
        keepdims: If this is set to `True`, the axes which are reduced are left
            in the result as dimensions with size one.

    Note:
        For values of `ord < 1`, the result is, strictly speaking, not a
        mathematical 'norm', but it may still be useful for various numerical
        purposes. The following norms can be calculated:
        - For matrices:
            - `ord=None`: Frobenius norm
            - `ord="fro"`: Frobenius norm
            - `ord=nuc`: nuclear norm
            - `ord=np.inf`: `max(sum(abs(x), axis=1))`
            - `ord=-np.inf`: `min(sum(abs(x), axis=1))`
            - `ord=0`: not supported
            - `ord=1`: `max(sum(abs(x), axis=0))`
            - `ord=-1`: `min(sum(abs(x), axis=0))`
            - `ord=2`: 2-norm (largest sing. value)
            - `ord=-2`: smallest singular value
            - other: not supported
        - For vectors:
            - `ord=None`: 2-norm
            - `ord="fro"`: not supported
            - `ord=nuc`: not supported
            - `ord=np.inf`: `max(abs(x))`
            - `ord=-np.inf`: `min(abs(x))`
            - `ord=0`: `sum(x != 0)`
            - `ord=1`: as below
            - `ord=-1`: as below
            - `ord=2`: as below
            - `ord=-2`: as below
            - other: `sum(abs(x)**ord)**(1./ord)`

    Returns:
        Norm of the matrix or vector(s).

    Example:

    >>> x = keras.ops.reshape(keras.ops.arange(9, dtype="float32") - 4, (3, 3))
    >>> keras.ops.linalg.norm(x)
    7.7459664
    """
    if any_symbolic_tensors((x,)):
        return Norm(ord=ord, axis=axis, keepdims=keepdims).symbolic_call(x)
    x = backend.convert_to_tensor(x)
    return backend.linalg.norm(x, ord=ord, axis=axis, keepdims=keepdims)


class Qr(Operation):
    def __init__(self, mode="reduced"):
        super().__init__()
        if mode not in {"reduced", "complete"}:
            raise ValueError(
                "`mode` argument value not supported. "
                "Expected one of {'reduced', 'complete'}. "
                f"Received: mode={mode}"
            )
        self.mode = mode

    def compute_output_spec(self, x):
        if len(x.shape) < 2:
            raise ValueError(
                "Input should have rank >= 2. Received: "
                f"input.shape = {x.shape}"
            )
        m = x.shape[-2]
        n = x.shape[-1]
        if m is None or n is None:
            raise ValueError(
                "Input should have its last 2 dimensions "
                "fully-defined. Received: "
                f"input.shape = {x.shape}"
            )
        k = min(m, n)
        base = tuple(x.shape[:-2])
        if self.mode == "reduced":
            return (
                KerasTensor(shape=base + (m, k), dtype=x.dtype),
                KerasTensor(shape=base + (k, n), dtype=x.dtype),
            )
        # 'complete' mode.
        return (
            KerasTensor(shape=base + (m, m), dtype=x.dtype),
            KerasTensor(shape=base + (m, n), dtype=x.dtype),
        )

    def call(self, x):
        return backend.linalg.qr(x, mode=self.mode)


@keras_export("keras.ops.linalg.qr")
def qr(x, mode="reduced"):
    """Computes the QR decomposition of a tensor.

    Args:
        x: Input tensor.
        mode: A string specifying the mode of the QR decomposition.
            - 'reduced': Returns the reduced QR decomposition. (default)
            - 'complete': Returns the complete QR decomposition.

    Returns:
        A tuple containing two tensors. The first tensor represents the
        orthogonal matrix Q, and the second tensor represents the upper
        triangular matrix R.

    Example:

    >>> x = keras.ops.convert_to_tensor([[1., 2.], [3., 4.], [5., 6.]])
    >>> q, r = qr(x)
    >>> print(q)
    array([[-0.16903079  0.897085]
           [-0.5070925   0.2760267 ]
           [-0.8451542  -0.34503305]], shape=(3, 2), dtype=float32)
    """

    if any_symbolic_tensors((x,)):
        return Qr(mode=mode).symbolic_call(x)
    return backend.linalg.qr(x, mode=mode)


class Solve(Operation):

    def __init__(self):
        super().__init__()

    def call(self, a, b):
        return _solve(a, b)

    def compute_output_spec(self, a, b):
        _assert_2d(a)
        _assert_square(a)
        _assert_1d(b)
        _assert_a_b_compat(a, b)
        return KerasTensor(b.shape, b.dtype)


@keras_export("keras.ops.linalg.solve")
def solve(a, b):
    """Solves a linear system of equations given by `a x = b`.

    Args:
        a: A tensor of shape (..., M, M) representing the coefficients matrix.
        b: A tensor of shape (..., M) or (..., M, K) represeting the right-hand side or "dependent variable" matrix.

    Returns:
        A tensor of shape (..., M) or (..., M, K) representing the solution of the
        linear system. Returned shape is identical to `b`.

    """
    if any_symbolic_tensors((a, b)):
        return Solve().symbolic_call(a, b)
    return _solve(a, b)


def _solve(a, b):
    a = backend.convert_to_tensor(a)
    b = backend.convert_to_tensor(b)
    _assert_2d(a)
    _assert_square(a)
    _assert_1d(b)
    _assert_a_b_compat(a, b)
    return backend.linalg.solve(a, b)




class SVD(Operation):

    def __init__(self):
        super().__init__()

    def call(self, x):
        return _svd(x)

    def compute_output_spec(self, x):
        _assert_2d(x)
        return (
            KerasTensor(x.shape, x.dtype),
            KerasTensor(x.shape, x.dtype),
            KerasTensor(x.shape, x.dtype),
        )


@keras_export("keras.ops.linalg.svd")
def svd(x):
    """Computes the singular value decomposition of a matrix.

    Args:
        x: A tensor of shape (..., M, N).

    Returns:
        A tuple of three tensors: a tensor of shape (..., M, M) containing the
        left singular vectors, a tensor of shape (..., M, N) containing the
        singular values and a tensor of shape (..., N, N) containing the
        right singular vectors.

    """
    if any_symbolic_tensors((x,)):
        return SVD().symbolic_call(x)
    return _svd(x)


def _svd(x):
    x = backend.convert_to_tensor(x)
    _assert_2d(x)
    return backend.linalg.svd(x)




def _assert_1d(*arrays):
    for a in arrays:
        if a.ndim < 1:
            raise LinalgError(
                f"{a.ndim}-dimensional array given. Array must be "
                "at least one-dimensional"
            )


def _assert_2d(*arrays):
    for a in arrays:
        if a.ndim < 2:
            raise LinalgError(
                f"{a.ndim}-dimensional array given. Array must be "
                "at least two-dimensional"
            )


def _assert_square(*arrays):
    for a in arrays:
        m, n = a.shape[-2:]
        if m != n:
            raise LinalgError("Last 2 dimensions of the array must be square")


def _assert_a_b_compat(a, b):
    if a.ndim == b.ndim:
        if a.shape[-2] != b.shape[-2]:
            raise LinalgError(
                f"Incompatible shapes between `a` {a.shape} and `b` {b.shape}"
            )
    elif a.ndim == b.ndim - 1:
        if a.shape[-1] != b.shape[-1]:
            raise LinalgError(
                f"Incompatible shapes between `a` {a.shape} and `b` {b.shape}"
            )
