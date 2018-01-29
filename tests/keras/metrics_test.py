import pytest
import numpy as np

from keras import metrics
from keras import backend as K

all_metrics = [
    metrics.binary_accuracy,
    metrics.categorical_accuracy,
    metrics.mean_squared_error,
    metrics.mean_absolute_error,
    metrics.mean_absolute_percentage_error,
    metrics.mean_squared_logarithmic_error,
    metrics.squared_hinge,
    metrics.hinge,
    metrics.categorical_crossentropy,
    metrics.binary_crossentropy,
    metrics.poisson,
    metrics.cosine_proximity,
    metrics.logcosh,
]

all_sparse_metrics = [
    metrics.sparse_categorical_accuracy,
    metrics.sparse_categorical_crossentropy,
]

all_stateful_metrics = [
    metrics.TruePositives()
]


def test_metrics():
    y_a = K.variable(np.random.random((6, 7)))
    y_b = K.variable(np.random.random((6, 7)))
    for metric in all_metrics:
        output = metric(y_a, y_b)
        print(metric.__name__)
        assert K.eval(output).shape == (6,)


def test_sparse_metrics():
    for metric in all_sparse_metrics:
        y_a = K.variable(np.random.randint(0, 7, (6,)), dtype=K.floatx())
        y_b = K.variable(np.random.random((6, 7)), dtype=K.floatx())
        assert K.eval(metric(y_a, y_b)).shape == (6,)


def test_serialize():
    '''This is a mock 'round trip' of serialize and deserialize.
    '''

    class MockMetric:
        def __init__(self):
            self.__name__ = "mock_metric"

    mock = MockMetric()
    found = metrics.serialize(mock)
    assert found == "mock_metric"

    found = metrics.deserialize('mock_metric',
                                custom_objects={'mock_metric': True})
    assert found is True


def test_invalid_get():

    with pytest.raises(ValueError):
        metrics.get(5)


def test_stateful_metric_inheritance():
    for metric in all_stateful_metrics:
        assert isinstance(metric, metrics.StatefulMetric)


def test_reset_states():
    # Test each stateful metric has implemented reset_states
    for metric in all_stateful_metrics:
        metric.reset_states()
    metrics.reset_stateful_metrics(all_metrics + all_stateful_metrics)


def test_get_stateful_metrics():
    # Case 1: No metrics
    metric_lst = None
    stateful_metrics, stateful_metric_names = metrics.get_stateful_metrics(metric_lst)
    assert stateful_metrics == []
    assert stateful_metric_names == []

    metric_lst = []
    stateful_metrics, stateful_metric_names = metrics.get_stateful_metrics(metric_lst)
    assert stateful_metrics == []
    assert stateful_metric_names == []

    # Case 2: Only non-Stateful Metrics
    metric_lst = all_metrics
    stateful_metrics, stateful_metric_names = metrics.get_stateful_metrics(metric_lst)
    assert stateful_metrics == []
    assert stateful_metric_names == []

    # Case 3: Only Stateful Metrics
    metric_lst = all_stateful_metrics
    stateful_metrics, stateful_metric_names = metrics.get_stateful_metrics(metric_lst)
    assert stateful_metrics == all_stateful_metrics
    assert stateful_metric_names == [metrics.serialize(m) for m in all_stateful_metrics]

    # Case 4: Mixture of non-Stateful and Stateful Metrics
    metric_lst = all_metrics + all_stateful_metrics
    stateful_metrics, stateful_metric_names = metrics.get_stateful_metrics(metric_lst)
    assert stateful_metrics == all_stateful_metrics
    assert stateful_metric_names == [metrics.serialize(m) for m in all_stateful_metrics]


def test_TruePositives():


@pytest.mark.skipif((K.backend() == 'cntk'),
                    reason="keras cntk backend does not support top_k yet")
def test_top_k_categorical_accuracy():
    y_pred = K.variable(np.array([[0.3, 0.2, 0.1], [0.1, 0.2, 0.7]]))
    y_true = K.variable(np.array([[0, 1, 0], [1, 0, 0]]))
    success_result = K.eval(metrics.top_k_categorical_accuracy(y_true, y_pred,
                                                               k=3))
    assert success_result == 1
    partial_result = K.eval(metrics.top_k_categorical_accuracy(y_true, y_pred,
                                                               k=2))
    assert partial_result == 0.5
    failure_result = K.eval(metrics.top_k_categorical_accuracy(y_true, y_pred,
                                                               k=1))
    assert failure_result == 0


@pytest.mark.skipif((K.backend() == 'cntk'),
                    reason="keras cntk backend does not support top_k yet")
def test_sparse_top_k_categorical_accuracy():
    y_pred = K.variable(np.array([[0.3, 0.2, 0.1], [0.1, 0.2, 0.7]]))
    y_true = K.variable(np.array([[1], [0]]))
    success_result = K.eval(
        metrics.sparse_top_k_categorical_accuracy(y_true, y_pred, k=3))

    assert success_result == 1
    partial_result = K.eval(
        metrics.sparse_top_k_categorical_accuracy(y_true, y_pred, k=2))

    assert partial_result == 0.5
    failure_result = K.eval(
        metrics.sparse_top_k_categorical_accuracy(y_true, y_pred, k=1))

    assert failure_result == 0


if __name__ == '__main__':
    pytest.main([__file__])
