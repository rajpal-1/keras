import contextlib
from unittest.mock import Mock

import numpy as np
import pytest
import tree
from absl.testing import parameterized

from keras import backend
from keras import layers
from keras import losses
from keras import models
from keras import ops
from keras import optimizers
from keras import testing
from keras.backend.common.keras_tensor import KerasTensor
from keras.backend.common.variables import ALLOWED_DTYPES
from keras.ops import core


class CoreOpsStaticShapeTest(testing.TestCase):
    def test_scatter(self):
        indices = KerasTensor((5, 2))
        values = KerasTensor((5,))
        shape = (4, 4)
        self.assertEqual(core.scatter(indices, values, shape).shape, (4, 4))

    def test_scatter_update(self):
        inputs = KerasTensor((4, 4))
        indices = KerasTensor((5, 2))
        updates = KerasTensor((5,))
        self.assertEqual(
            core.scatter_update(inputs, indices, updates).shape, (4, 4)
        )

        inputs = KerasTensor((4, 4, 4))
        indices = KerasTensor((5, 2))
        updates = KerasTensor((5, 4))
        self.assertEqual(
            core.scatter_update(inputs, indices, updates).shape, (4, 4, 4)
        )

    def test_slice_update(self):
        inputs = KerasTensor((4, 4))
        start_indices = KerasTensor((2,))
        updates = KerasTensor((2, 2))
        self.assertEqual(
            core.slice_update(inputs, start_indices, updates).shape, (4, 4)
        )

        inputs = KerasTensor((4, 4, 4))
        start_indices = KerasTensor((3,))
        updates = KerasTensor((2, 2, 2))
        self.assertEqual(
            core.slice_update(inputs, start_indices, updates).shape, (4, 4, 4)
        )

    def test_fori_loop(self):
        def body_fun(i, x):
            return x + i

        initial_value = KerasTensor((3, 5, 7))
        result = core.fori_loop(0, 10, body_fun, initial_value)
        self.assertEqual(result.shape, (3, 5, 7))

    def test_unstack(self):
        x = KerasTensor((2, 3, 4))
        axis = 1
        out = core.unstack(x, axis=axis)
        self.assertEqual(len(out), 3)
        for o in out:
            self.assertEqual(o.shape, (2, 4))

        x = KerasTensor((2, None, None))
        axis, num = 1, 3
        out = core.unstack(x, num=num, axis=axis)
        self.assertEqual(len(out), 3)
        for o in out:
            self.assertEqual(o.shape, (2, None))

        with self.assertRaisesRegex(
            ValueError, r"Cannot infer argument `num` from shape"
        ):
            core.unstack(x, axis=axis)


class CoreOpsCorrectnessTest(testing.TestCase, parameterized.TestCase):
    def test_scatter(self):
        # Test 1D
        indices = np.array([[1], [3], [4], [7]])
        values = np.array([9, 10, 11, 12])
        self.assertAllClose(
            core.scatter(indices, values, (8,)),
            [0, 9, 0, 10, 11, 0, 0, 12],
        )
        # Test 2D
        indices = np.array([[0, 1], [2, 0]])
        values = np.array([5, 10])
        self.assertAllClose(
            core.scatter(indices, values, (3, 2)), [[0, 5], [0, 0], [10, 0]]
        )
        # Test 3D
        indices = np.array([[1], [3]])
        values = np.array(
            [
                [[5, 5, 5, 5], [6, 6, 6, 6], [7, 7, 7, 7], [8, 8, 8, 8]],
                [[5, 5, 5, 5], [6, 6, 6, 6], [7, 7, 7, 7], [8, 8, 8, 8]],
            ]
        )
        self.assertAllClose(
            core.scatter(indices, values, (4, 4, 4)),
            [
                [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                [[5, 5, 5, 5], [6, 6, 6, 6], [7, 7, 7, 7], [8, 8, 8, 8]],
                [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                [[5, 5, 5, 5], [6, 6, 6, 6], [7, 7, 7, 7], [8, 8, 8, 8]],
            ],
        )
        # Test slices
        indices = np.array([[2], [4]])
        values = np.array([[1, 2, 3], [4, 5, 6]])
        self.assertAllClose(
            core.scatter(indices, values, (6, 3)),
            [[0, 0, 0], [0, 0, 0], [1, 2, 3], [0, 0, 0], [4, 5, 6], [0, 0, 0]],
        )
        # Duplicate indices
        indices = np.array([[0], [0]])
        values = np.array([1, 1])
        self.assertAllClose(core.scatter(indices, values, (1,)), [2])

    def test_scatter_update(self):
        # Test 1D.
        inputs = np.array([0, 0, 0, 0, 0, 0, 0, 0])
        indices = [[1], [3], [4], [7]]
        updates = np.array([9, 10, 11, 12])
        self.assertAllClose(
            core.scatter_update(inputs, indices, updates),
            [0, 9, 0, 10, 11, 0, 0, 12],
        )

        # Test 2D.
        inputs = np.array([[1, 1], [1, 1], [1, 1]])
        indices = [[0, 1], [2, 0]]
        updates = np.array([5, 10])
        self.assertAllClose(
            core.scatter_update(inputs, indices, updates),
            [[1, 5], [1, 1], [10, 1]],
        )

        # Test updates has multiple dimension.
        inputs = np.ones([4, 4, 4])
        indices = [[1, 1], [2, 2]]
        updates = np.array([[0, 1, 2, 3], [3, 2, 1, 0]], dtype=np.float64)
        outputs = core.scatter_update(inputs, indices, updates)
        self.assertTrue(ops.is_tensor(outputs))
        self.assertAllClose(outputs[1, 1, :], [0, 1, 2, 3])
        self.assertAllClose(outputs[2, 2, :], [3, 2, 1, 0])

    def test_slice(self):
        # Test 1D.
        inputs = np.arange(10)
        start_indices = np.array([1])
        shape = np.array([4])
        self.assertAllClose(
            core.slice(inputs, start_indices, shape),
            [1, 2, 3, 4],
        )

        # Test 2D.
        inputs = np.broadcast_to(np.arange(10), (4, 10))
        start_indices = np.array([1, 1])
        shape = np.array([2, 4])
        self.assertAllClose(
            core.slice(inputs, start_indices, shape),
            [[1, 2, 3, 4], [1, 2, 3, 4]],
        )

        # Test N-D.
        inputs = np.broadcast_to(np.arange(10), (4, 4, 4, 10))
        start_indices = np.array([1, 1, 1, 1])
        shape = np.array([1, 2, 3, 4])
        outputs = core.slice(inputs, start_indices, shape)
        expected = np.broadcast_to(np.arange(1, 5), (1, 2, 3, 4))
        self.assertAllClose(outputs, expected)

    def test_dynamic_slice(self):
        def cond(index, inputs, sum):
            return index < 10

        def body(index, inputs, sum):
            sum = sum + core.slice(inputs, [index], [1])
            index = index + 1
            return index, inputs, sum

        index, inputs, sum = 0, np.arange(10), np.array([0])
        index, inputs, sum = core.while_loop(cond, body, (index, inputs, sum))
        self.assertAllClose(sum, [45])

    def test_slice_update(self):
        # Test 1D.
        inputs = np.array([0, 0, 0, 0, 0, 0, 0, 0])
        start_indices = np.array([1])
        updates = np.array([9, 10, 11, 12])
        self.assertAllClose(
            core.slice_update(inputs, start_indices, updates),
            [0, 9, 10, 11, 12, 0, 0, 0],
        )

        # Test 2D.
        inputs = np.array([[1, 1], [1, 1], [1, 1]])
        start_indices = [1, 0]
        updates = np.array([[2, 2], [2, 2]])
        self.assertAllClose(
            core.slice_update(inputs, start_indices, updates),
            [[1, 1], [2, 2], [2, 2]],
        )

        # Test N-D.
        inputs = np.ones([4, 4, 4, 4])
        start_indices = [1, 1, 2, 2]
        updates = np.zeros([2, 2, 2, 2])
        outputs = core.slice_update(inputs, start_indices, updates)
        self.assertAllClose(outputs[1:3, 1:3, 2:4, 2:4], np.zeros([2, 2, 2, 2]))

    @parameterized.named_parameters(
        [
            {
                "testcase_name": "with_max",
                "state": (np.array(0), np.array(1)),
                "output": (np.array(5), np.array(6)),
                "maximum_iterations": 5,
            },
            {
                "testcase_name": "no_max",
                "state": (np.array(0), np.array(1)),
                "output": (np.array(10), np.array(11)),
                "maximum_iterations": None,
            },
        ]
    )
    def test_while_loop_list_data(self, state, output, maximum_iterations):
        def cond(*args):
            return tree.flatten(args)[0] < 10

        def body(*args):
            return tree.map_structure(lambda x: x + 1, args)

        state = core.while_loop(
            cond, body, state, maximum_iterations=maximum_iterations
        )
        tree.map_structure(self.assertAllClose, state, output)

    @parameterized.named_parameters(
        [
            {
                "testcase_name": "scalar_data_with_max",
                "state": np.array(0),
                "output": np.array(5),
                "maximum_iterations": 5,
            },
            {
                "testcase_name": "scalar_data_no_max",
                "state": np.array(0),
                "output": np.array(10),
                "maximum_iterations": None,
            },
            {
                "testcase_name": "nested_data_with_max",
                "state": {
                    "a": np.array(0),
                    "b": (np.array(1), np.array(2)),
                },
                "output": {
                    "a": np.array(5),
                    "b": (np.array(6), np.array(7)),
                },
                "maximum_iterations": 5,
            },
            {
                "testcase_name": "nested_data_no_max",
                "state": {
                    "a": np.array(0),
                    "b": (np.array(1), np.array(2)),
                },
                "output": {
                    "a": np.array(10),
                    "b": (np.array(11), np.array(12)),
                },
                "maximum_iterations": None,
            },
        ]
    )
    def test_while_loop(self, state, output, maximum_iterations):
        def cond(args):
            return tree.flatten(args)[0] < 10

        def body(args):
            return tree.map_structure(lambda x: x + 1, args)

        state = core.while_loop(
            cond, body, state, maximum_iterations=maximum_iterations
        )
        tree.map_structure(self.assertAllClose, state, output)

    def test_fori_loop(self):
        def body_fun(i, x):
            return x + i

        initial_value = np.array(0)
        result = core.fori_loop(0, 10, body_fun, initial_value)
        self.assertAllClose(result, 45)

    @pytest.mark.requires_trainable_backend
    def test_stop_gradient(self):
        class ExampleLayer(layers.Layer):
            def __init__(self):
                super().__init__()
                self.w = self.add_weight(shape=(1,), initializer="zeros")
                self.b = self.add_weight(shape=(1,), initializer="zeros")

            def call(self, x, training=False):
                return x * ops.stop_gradient(self.w.value) + self.b

        model = models.Sequential([ExampleLayer()])
        model.compile(
            optimizer=optimizers.SGD(), loss=losses.MeanSquaredError()
        )
        rng = np.random.default_rng(0)
        x = np.ones((2, 4), dtype=np.float32)
        y = rng.standard_normal((2, 4), dtype=np.float32)
        model.fit(x, y, epochs=1, batch_size=2)
        self.assertEqual(model.layers[0].w.numpy(), 0.0)
        self.assertNotEqual(model.layers[0].b.numpy(), 0.0)

    def test_stop_gradient_return(self):
        x = ops.random.uniform(shape=(2, 4), dtype="float32")
        y = ops.stop_gradient(x)
        self.assertAllClose(x, y)

    def test_shape(self):
        x = np.ones((2, 3, 7, 1))
        self.assertAllEqual(core.shape(x), (2, 3, 7, 1))

        x = KerasTensor((None, 3, None, 1))
        self.assertAllEqual(core.shape(x), (None, 3, None, 1))

    @pytest.mark.skipif(
        not backend.SUPPORTS_SPARSE_TENSORS,
        reason="Backend does not support sparse tensors.",
    )
    def test_shape_sparse(self):
        if backend.backend() == "tensorflow":
            import tensorflow as tf

            x = tf.SparseTensor([[0, 0], [1, 2]], [1.0, 2.0], (2, 3))
        elif backend.backend() == "jax":
            import jax.experimental.sparse as jax_sparse

            x = jax_sparse.BCOO(([1.0, 2.0], [[0, 0], [1, 2]]), shape=(2, 3))
        else:
            self.fail(f"Sparse is unsupported with backend {backend.backend()}")

        self.assertAllEqual(core.shape(x), (2, 3))

    def test_convert_to_tensor(self):
        x = np.ones((2,))
        x = ops.convert_to_tensor(x)
        x = ops.convert_to_numpy(x)
        self.assertAllEqual(x, (1, 1))
        self.assertIsInstance(x, np.ndarray)

        # Empty lists should give an empty array.
        x = ops.convert_to_tensor([])
        np_x = ops.convert_to_numpy(x)
        self.assertTrue(ops.is_tensor(x))
        self.assertAllEqual(x, [])
        self.assertIsInstance(np_x, np.ndarray)

        # Partially converted.
        x = ops.convert_to_tensor((1, ops.array(2), 3))
        self.assertAllEqual(x, (1, 2, 3))

        with self.assertRaises(ValueError):
            ops.convert_to_numpy(KerasTensor((2,)))

    @pytest.mark.skipif(
        not backend.SUPPORTS_SPARSE_TENSORS,
        reason="Backend does not support sparse tensors.",
    )
    def test_convert_to_tensor_sparse(self):
        if backend.backend() == "tensorflow":
            import tensorflow as tf

            x = tf.SparseTensor([[0, 0], [1, 2]], [1.0, 2.0], (2, 3))
            sparse_class = tf.SparseTensor
        elif backend.backend() == "jax":
            import jax.experimental.sparse as jax_sparse

            x = jax_sparse.BCOO(([1.0, 2.0], [[0, 0], [1, 2]]), shape=(2, 3))
            sparse_class = jax_sparse.JAXSparse
        else:
            self.fail(f"Sparse is unsupported with backend {backend.backend()}")

        x_default = ops.convert_to_tensor(x)
        self.assertIsInstance(x_default, sparse_class)
        self.assertAllClose(x, x_default)
        x_sparse = ops.convert_to_tensor(x, sparse=True)
        self.assertIsInstance(x_sparse, sparse_class)
        self.assertAllClose(x, x_sparse)
        x_dense = ops.convert_to_tensor(x, sparse=False)
        self.assertNotIsInstance(x_dense, sparse_class)
        self.assertAllClose(x, x_dense)

        x_numpy = ops.convert_to_numpy(x)
        self.assertIsInstance(x_numpy, np.ndarray)
        self.assertAllClose(x_numpy, x_dense)

    def test_cond(self):
        t = ops.cond(True, lambda: 0, lambda: 1)
        self.assertEqual(t, 0)
        f = ops.cond(False, lambda: 0, lambda: 1)
        self.assertEqual(f, 1)
        f = ops.cond(False, lambda: None, lambda: None)
        self.assertEqual(f, None)

        for val in [True, False]:
            out = ops.cond(
                val,
                lambda: KerasTensor((16, 3)),
                lambda: KerasTensor((16, 3)),
            )
            self.assertEqual((16, 3), out.shape)

        out = ops.cond(
            KerasTensor((), dtype="bool"),
            lambda: ops.ones((1, 3)),
            lambda: ops.zeros((1, 3)),
        )
        self.assertEqual((1, 3), out.shape)

        out = ops.cond(
            KerasTensor((), dtype="bool"),
            lambda: KerasTensor((3,)),
            lambda: KerasTensor((3,)),
        )
        self.assertEqual((3,), out.shape)

        with self.assertRaises(ValueError):
            ops.cond(
                KerasTensor((), dtype="bool"),
                lambda: KerasTensor((3,)),
                lambda: KerasTensor((4,)),
            )

    def test_unstack(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(size=(2, 3, 4))
        x_tensor = ops.convert_to_tensor(x)
        axis = 1
        out = ops.unstack(x_tensor, axis=axis)
        out_ex = [x[:, i, :] for i in range(x.shape[axis])]
        self.assertEqual(len(out), len(out_ex))
        for o, o_e in zip(out, out_ex):
            o = ops.convert_to_numpy(o)
            self.assertAllClose(o, o_e)

    def test_cast(self):
        x = ops.ones((2,), dtype="float32")
        y = ops.cast(x, "float16")
        self.assertIn("float16", str(y.dtype))

        x = ops.KerasTensor((2,), dtype="float32")
        y = ops.cast(x, "float16")
        self.assertEqual("float16", y.dtype)
        self.assertEqual(x.shape, y.shape)
        self.assertTrue(hasattr(y, "_keras_history"))

    def test_vectorized_map(self):
        def fn(x):
            return x + 1

        output = ops.vectorized_map(fn, ops.zeros((2, 3), dtype="float32"))
        self.assertAllClose(backend.convert_to_numpy(output), np.ones((2, 3)))

        def fn(x):
            return ops.stack([x, x])

        output = ops.vectorized_map(fn, ops.zeros((2, 3), dtype="float32"))
        self.assertAllClose(
            backend.convert_to_numpy(output), np.zeros((2, 2, 3))
        )

        # Case: multiple args
        def fn(elems):
            x, y = elems
            return x + y

        output = ops.vectorized_map(fn, [ops.ones((2, 3)), ops.ones((2, 3))])
        self.assertAllClose(
            backend.convert_to_numpy(output), 2 * np.ones((2, 3))
        )

    def test_is_tensor(self):
        np_x = np.array([[1, 2, 3], [3, 2, 1]])
        x = backend.convert_to_tensor(np_x)
        if backend.backend() != "numpy":
            self.assertFalse(ops.is_tensor(np_x))
        self.assertTrue(ops.is_tensor(x))
        self.assertFalse(ops.is_tensor([1, 2, 3]))


class CoreOpsDtypeTest(testing.TestCase, parameterized.TestCase):
    import jax  # enable bfloat16 for numpy

    # TODO: Using uint64 will lead to weak type promotion (`float`),
    # resulting in different behavior between JAX and Keras. Currently, we
    # are skipping the test for uint64
    ALL_DTYPES = [
        x for x in ALLOWED_DTYPES if x not in ["string", "uint64"]
    ] + [None]

    if backend.backend() == "torch":
        # TODO: torch doesn't support uint16, uint32 and uint64
        ALL_DTYPES = [
            x for x in ALL_DTYPES if x not in ["uint16", "uint32", "uint64"]
        ]

    @parameterized.parameters(
        ((), None, backend.floatx()),
        ([], None, backend.floatx()),
        (bool(0), None, "bool"),
        (int(0), None, "int32"),
        (float(0), None, backend.floatx()),
        ([False, True, False], None, "bool"),
        ([1, 2, 3], None, "int32"),
        ([1.0, 2.0, 3.0], None, backend.floatx()),
        ([1, 2.0, 3], None, backend.floatx()),
        ([[False], [True], [False]], None, "bool"),
        ([[1], [2], [3]], None, "int32"),
        ([[1], [2.0], [3]], None, backend.floatx()),
        *[
            (np.array(0, dtype=dtype), None, dtype)
            for dtype in ALL_DTYPES
            if dtype is not None
        ],
        *[
            ([[1, 0, 1], [1, 1, 0]], dtype, dtype)
            for dtype in ALL_DTYPES
            if dtype is not None
        ],
    )
    def test_convert_to_tensor(self, x, dtype, expected_dtype):
        # We have to disable x64 for jax backend since jnp.array doesn't respect
        # JAX_DEFAULT_DTYPE_BITS=32 in `./conftest.py`. We also need to downcast
        # the expected dtype from 64 bit to 32 bit.
        if backend.backend() == "jax":
            import jax.experimental

            jax_disable_x64 = jax.experimental.disable_x64()
            expected_dtype = expected_dtype.replace("64", "32")
        else:
            jax_disable_x64 = contextlib.nullcontext()

        with jax_disable_x64:
            self.assertEqual(
                backend.standardize_dtype(
                    ops.convert_to_tensor(x, dtype=dtype).dtype
                ),
                expected_dtype,
            )


class CoreOpsCallsTests(testing.TestCase):
    def test_scatter_basic_call(self):
        indices = np.array([[1, 0], [0, 1]])
        values = np.array([10, 20])
        shape = (2, 2)
        scatter = core.Scatter()
        result = scatter.call(indices, values, shape)
        expected_output = np.array([[0, 20], [10, 0]])
        self.assertAllClose(core.convert_to_numpy(result), expected_output)

    def test_scatter_update_basic_call(self):
        inputs = np.array([[0, 0], [0, 0]])
        indices = np.array([[1, 0], [0, 1]])
        updates = np.array([10, 20])
        scatter_update = core.ScatterUpdate()
        result = scatter_update.call(inputs, indices, updates)
        expected_output = np.array([[0, 20], [10, 0]])
        self.assertAllClose(core.convert_to_numpy(result), expected_output)

    def test_slice_basic_call(self):
        inputs = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        start_indices = np.array([1, 1])
        shape = (2, 2)
        slice_op = core.Slice()
        result = slice_op.call(inputs, start_indices, shape)
        expected_output = np.array([[5, 6], [8, 9]])
        self.assertAllClose(core.convert_to_numpy(result), expected_output)

    def test_slice_compute_output_spec(self):
        inputs = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32)
        start_indices = np.array([1, 1])
        shape = (2, 2)
        slice_op = core.Slice()
        output_spec = slice_op.compute_output_spec(inputs, start_indices, shape)
        self.assertEqual(output_spec.shape, shape)
        self.assertEqual(output_spec.dtype, inputs.dtype)

    def test_slice_with_symbolic_tensors(self):
        inputs = KerasTensor(shape=(3, 3), dtype=np.float32)
        start_indices = KerasTensor(shape=(2,), dtype=np.int32)
        shape = (2, 2)
        result = core.slice(inputs, start_indices, shape)
        self.assertTrue(isinstance(result, KerasTensor))

    def test_slice_with_non_symbolic_tensors(self):
        inputs = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        start_indices = np.array([1, 1])
        shape = (2, 2)
        result = core.slice(inputs, start_indices, shape)
        expected_output = np.array([[5, 6], [8, 9]])
        self.assertAllClose(result, expected_output)

    def test_slice_update_basic_call(self):
        inputs = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        start_indices = np.array([1, 1])
        updates = np.array([[10, 11], [12, 13]])
        slice_update = core.SliceUpdate()
        result = slice_update.call(inputs, start_indices, updates)
        expected_output = np.array([[1, 2, 3], [4, 10, 11], [7, 12, 13]])
        self.assertAllClose(core.convert_to_numpy(result), expected_output)

    def test_while_loop_basic_functionality(self):
        # Loop condition: continue if i < 5
        def cond(i):
            return i < 5

        # Loop body: increment i by 1
        def body(i):
            return (i + 1,)

        while_loop = core.WhileLoop(cond, body, maximum_iterations=None)
        # Initial loop variable (i = 0)
        loop_vars = (0,)
        result = while_loop.call(loop_vars)
        self.assertEqual(result[0], 5)

    def test_while_loop_output_spec(self):
        # Define dummy cond and body functions
        def cond(x):
            return True

        def body(x):
            return (x,)

        while_loop = core.WhileLoop(cond, body, maximum_iterations=None)
        loop_vars = (KerasTensor(shape=(10,), dtype=np.float32),)
        output_spec = while_loop.compute_output_spec(loop_vars)
        self.assertEqual(output_spec[0].shape, loop_vars[0].shape)
        self.assertEqual(output_spec[0].dtype, loop_vars[0].dtype)

    def test_while_loop_with_max_iterations(self):
        # loop condition: continue if i < 10
        def cond(i):
            return i < 10

        def body(i):
            return (i + 1,)

        while_loop = core.WhileLoop(cond, body, maximum_iterations=5)
        result = while_loop.call((0,))
        self.assertEqual(result[0], 5)

    def test_whileloop_compute_output_spec(self):
        # Define loop variables with different shapes and data types
        loop_vars = (np.random.rand(5, 5), np.random.randint(10, size=(3, 7)))
        keras_loop_vars = [
            KerasTensor(v.shape, dtype=v.dtype) for v in loop_vars
        ]

        def cond(v):
            return v[0] < 5

        def body(v):
            return (v[0] + 1, v[1])

        while_loop = core.WhileLoop(cond, body, maximum_iterations=None)
        output_specs = while_loop.compute_output_spec(keras_loop_vars)
        self.assertEqual(output_specs[0].shape, keras_loop_vars[0].shape)
        self.assertEqual(output_specs[0].dtype, keras_loop_vars[0].dtype)
        self.assertEqual(output_specs[1].shape, keras_loop_vars[1].shape)
        self.assertEqual(output_specs[1].dtype, keras_loop_vars[1].dtype)

    def test_stop_gradient_call(self):
        variable_np = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        variable = core.convert_to_tensor(variable_np)
        stop_gradient = core.StopGradient()
        result = stop_gradient.call(variable)
        result_np = core.convert_to_numpy(result)
        self.assertTrue(np.array_equal(result_np, variable_np))
        self.assertEqual(result_np.dtype, variable_np.dtype)

    def test_stop_gradient_compute_output_spec(self):
        variable = KerasTensor(shape=(3,), dtype=np.float32)
        stop_gradient = core.StopGradient()
        output_spec = stop_gradient.compute_output_spec(variable)
        self.assertEqual(output_spec.shape, variable.shape)
        self.assertEqual(output_spec.dtype, variable.dtype)

    def test_fori_loop_basic_functionality(self):
        lower = 0
        upper = 5

        def body_fun(index, val):
            return val + 1

        fori_loop = core.ForiLoop(lower, upper, body_fun)
        init_val = 0
        result = fori_loop.call(init_val)
        self.assertEqual(result, upper)

    def test_unstack_basic_functionality(self):
        x = np.random.rand(2, 3, 4)
        x = core.convert_to_tensor(x)
        axis = 1
        unstack = core.Unstack(axis=axis)
        result = unstack.call(x)
        self.assertEqual(len(result), x.shape[axis])
        result = core.convert_to_numpy(result)
        expected_shape = x.shape[:axis] + x.shape[axis + 1 :]
        # Check that all tensors have the same shape
        if len(result) > 0:
            self.assertEqual(result[0].shape, expected_shape)
        if len(result) > 1:
            self.assertEqual(result[1].shape, expected_shape)
        if len(result) > 2:
            self.assertEqual(result[2].shape, expected_shape)

    def test_cast_basic_functionality(self):
        x = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        target_dtype = np.int32
        cast = core.Cast(target_dtype)
        result = cast.call(x)
        result = core.convert_to_numpy(result)
        self.assertEqual(result.dtype, target_dtype)
        # Check that the values are the same
        expected_values = x.astype(target_dtype)
        self.assertTrue(np.array_equal(result, expected_values))

    def test_cond_check_output_spec_list_tuple(self):
        cond_op = core.Cond()
        mock_spec = Mock(dtype="float32", shape=(2, 2))
        self.assertTrue(
            cond_op._check_output_spec(
                [mock_spec, mock_spec], [mock_spec, mock_spec]
            )
        )

    def test_cond_check_output_spec_other_types(self):
        cond_op = core.Cond()
        # Create mock objects with dtype and shape attributes
        mock_spec1 = Mock(dtype="float32", shape=(2, 2))
        mock_spec2 = Mock(dtype="float32", shape=(2, 2))
        self.assertTrue(cond_op._check_output_spec(mock_spec1, mock_spec2))

    def test_cond_check_output_spec_none(self):
        cond_op = core.Cond()
        self.assertTrue(cond_op._check_output_spec(None, None))
        self.assertFalse(
            cond_op._check_output_spec(
                None, Mock(dtype="float32", shape=(2, 2))
            )
        )
        self.assertFalse(
            cond_op._check_output_spec(
                Mock(dtype="float32", shape=(2, 2)), None
            )
        )

    def test_cond_check_output_spec_dict(self):
        cond_op = core.Cond()
        mock_spec = Mock(dtype="float32", shape=(2, 2))
        self.assertTrue(
            cond_op._check_output_spec({"a": mock_spec}, {"a": mock_spec})
        )
        self.assertFalse(
            cond_op._check_output_spec({"a": mock_spec}, {"b": mock_spec})
        )
        self.assertFalse(
            cond_op._check_output_spec(
                {"a": mock_spec}, {"a": mock_spec, "b": mock_spec}
            )
        )

    def test_cond_check_output_spec_list(self):
        cond_op = core.Cond()
        mock_spec = Mock(dtype="float32", shape=(2, 2))
        mock_spec_different = Mock(dtype="int32", shape=(3, 3))
        self.assertTrue(cond_op._check_output_spec([mock_spec], [mock_spec]))
        self.assertFalse(
            cond_op._check_output_spec(
                [mock_spec], [mock_spec, mock_spec_different]
            )
        )

    def test_cond_check_output_spec_tuple(self):
        cond_op = core.Cond()
        mock_spec = Mock(dtype="float32", shape=(2, 2))
        mock_spec_different = Mock(dtype="int32", shape=(3, 3))
        self.assertTrue(cond_op._check_output_spec((mock_spec,), (mock_spec,)))
        self.assertFalse(
            cond_op._check_output_spec(
                (mock_spec,), (mock_spec, mock_spec_different)
            )
        )

    def test_unstack_with_negative_axis_first_tensor(self):
        x = np.random.rand(4, 3, 2)
        x_tensor = ops.convert_to_tensor(x)
        negative_axis = -1
        result = ops.unstack(x_tensor, axis=negative_axis)
        expected_shape = (4, 3)
        self.assertAllEqual(result[0].shape, expected_shape)

    def test_unstack_with_negative_axis_second_tensor(self):
        x = np.random.rand(4, 3, 2)
        x_tensor = ops.convert_to_tensor(x)
        negative_axis = -1
        result = ops.unstack(x_tensor, axis=negative_axis)
        expected_shape = (4, 3)
        self.assertAllEqual(result[1].shape, expected_shape)

    def test_cond_output_spec_mismatch_true_fn_dict_false_fn_not_dict(self):
        cond_op = core.Cond()

        # true_fn returns a dictionary
        def true_fn():
            return {"a": KerasTensor(shape=(3, 3), dtype="float32")}

        # false_fn returns a non-dictionary type, e.g., a list
        def false_fn():
            return [KerasTensor(shape=(3, 3), dtype="float32")]

        pred = KerasTensor(shape=(), dtype="bool")  # Dummy predicate

        expected_regex = "should return outputs of the same kind"

        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_mismatch_in_dict_values(self):
        cond_op = core.Cond()

        def true_fn():
            return {
                "a": KerasTensor(shape=(3, 3), dtype="float32"),
                "b": KerasTensor(shape=(4, 4), dtype="float32"),
            }

        def false_fn():
            return {
                "a": KerasTensor(shape=(3, 3), dtype="float32"),
                # Mismatched shape
                "b": KerasTensor(shape=(2, 2), dtype="float32"),
            }

        pred = KerasTensor(shape=(), dtype="bool")
        expected_regex = "should return outputs of the same kind"
        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_mismatch_true_fn_list_false_fn_not_list(self):
        cond_op = core.Cond()

        def true_fn():
            return [
                KerasTensor(shape=(3, 3), dtype="float32"),
                KerasTensor(shape=(4, 4), dtype="float32"),
            ]

        def false_fn():
            return {
                "a": KerasTensor(shape=(3, 3), dtype="float32"),
                "b": KerasTensor(shape=(4, 4), dtype="float32"),
            }

        pred = KerasTensor(shape=(), dtype="bool")
        expected_regex = "should return outputs of the same kind"
        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_mismatch_in_list_elements(self):
        cond_op = core.Cond()

        def true_fn():
            return [
                KerasTensor(shape=(3, 3), dtype="float32"),
                KerasTensor(shape=(4, 4), dtype="float32"),
            ]

        def false_fn():
            return [
                KerasTensor(shape=(3, 3), dtype="float32"),
                # Mismatched shape
                KerasTensor(shape=(2, 2), dtype="float32"),
            ]

        pred = KerasTensor(shape=(), dtype="bool")
        expected_regex = "should return outputs of the same kind"

        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_mismatch_true_fn_tuple_false_fn_not_tuple(self):
        cond_op = core.Cond()

        def true_fn():
            return (
                KerasTensor(shape=(3, 3), dtype="float32"),
                KerasTensor(shape=(4, 4), dtype="float32"),
            )

        def false_fn():
            # not a tuple to match the true_fn
            return {
                "a": KerasTensor(shape=(3, 3), dtype="float32"),
                "b": KerasTensor(shape=(4, 4), dtype="float32"),
            }

        pred = KerasTensor(shape=(), dtype="bool")
        expected_regex = "should return outputs of the same kind"

        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_mismatch_in_tuple_elements(self):
        cond_op = core.Cond()

        def true_fn():
            return (
                KerasTensor(shape=(3, 3), dtype='float32'),
                KerasTensor(shape=(4, 4), dtype='float32'),
            )

        def false_fn():
            return (
                KerasTensor(shape=(3, 3), dtype='float32'),
                # Mismatched tuple
                KerasTensor(shape=(2, 2), dtype='float32'),
            )

        pred = KerasTensor(shape=(), dtype='bool')
        expected_regex = "should return outputs of the same kind"

        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)

    def test_cond_output_spec_dtype_mismatch(self):
        cond_op = core.Cond()

        def true_fn():
            return KerasTensor(shape=(3, 3), dtype='float32')

        def false_fn():
            # Mismatched dtype
            return KerasTensor(shape=(3, 3), dtype='int32')

        pred = KerasTensor(shape=(), dtype='bool')
        expected_regex = "(struct, dtype and shape)"

        with self.assertRaisesRegex(ValueError, expected_regex):
            cond_op(pred, true_fn, false_fn)
