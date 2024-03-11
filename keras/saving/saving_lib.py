"""Python-based idempotent model-saving functionality."""

import datetime
import io
import json
import tempfile
import warnings
import zipfile
import re
import os

import numpy as np

from keras.backend.common import global_state
from keras.layers.layer import Layer
from keras.losses.loss import Loss
from keras.metrics.metric import Metric
from keras.optimizers.optimizer import Optimizer
from keras.saving.serialization_lib import ObjectSharingScope
from keras.saving.serialization_lib import deserialize_keras_object
from keras.saving.serialization_lib import serialize_keras_object
from keras.trainers.compile_utils import CompileMetrics
from keras.utils import file_utils
from keras.utils import naming
from keras.version import __version__ as keras_version

try:
    import h5py
except ImportError:
    h5py = None

_CONFIG_FILENAME = "config.json"
_METADATA_FILENAME = "metadata.json"
_VARS_FNAME = "model.weights"  # Will become e.g. "model.weights.h5"
_ASSETS_DIRNAME = "assets"


def save_model(model, filepath, weights_format="h5", sharded=False, shard_size=None):
    """Save a zip-archive representing a Keras model to the given filepath.

    The zip-based archive contains the following structure:

    - JSON-based configuration file (config.json): Records of model, layer, and
        other trackables' configuration.
    - H5-based trackable state files, found in respective directories, such as
        model/states.npz, model/dense_layer/states.npz, etc.
    - Metadata file.

    The states of Keras trackables (layers, optimizers, loss, and metrics) are
    automatically saved as long as they can be discovered through the attributes
    returned by `dir(Model)`. Typically, the state includes the variables
    associated with the trackable, but some specially purposed layers may
    contain more such as the vocabularies stored in the hashmaps. The trackables
    define how their states are saved by exposing `save_state()` and
    `load_state()` APIs.

    For the case of layer states, the variables will be visited as long as
    they are either 1) referenced via layer attributes, or 2) referenced via a
    container (list, tuple, or dict), and the container is referenced via a
    layer attribute.
    """
    filepath = str(filepath)
    if not filepath.endswith(".keras"):
        raise ValueError(
            "Invalid `filepath` argument: expected a `.keras` extension. "
            f"Received: filepath={filepath}"
        )
    if weights_format == "h5" and h5py is None:
        raise ImportError("h5py must be installed in order to save a model.")
    if weights_format != "h5" and sharded:
        raise NotImplementedError(
            "Sharding is only currently supported in the H5 weights format. "
            "Please pass `sharded=False` or switch to `weights_format=h5`. "
            f"Received: weights_format={weights_format}, sharded={sharded}."
        )

    if not model.built:
        warnings.warn(
            "You are saving a model that has not yet been built. "
            "It might not contain any weights yet. "
            "Consider building the model first by calling it "
            "on some data.",
            stacklevel=2,
        )

    with ObjectSharingScope():
        serialized_model_dict = serialize_keras_object(model)
    config_json = json.dumps(serialized_model_dict)
    metadata_json = json.dumps(
        {
            "keras_version": keras_version,
            "date_saved": datetime.datetime.now().strftime("%Y-%m-%d@%H:%M:%S"),
        }
    )
    if file_utils.is_remote_path(filepath):
        # Remote path. Zip to local memory byte io and copy to remote
        zip_filepath = io.BytesIO()
    else:
        zip_filepath = filepath

    with zipfile.ZipFile(zip_filepath, "w") as zf:
        with zf.open(_METADATA_FILENAME, "w") as f:
            f.write(metadata_json.encode())
        with zf.open(_CONFIG_FILENAME, "w") as f:
            f.write(config_json.encode())

        if weights_format == "h5":
            if sharded:
                max_size = shard_size if shard_size is not None else "10GB"
                weights_store = ShardedH5IOStore(
                    _VARS_FNAME + ".h5",
                    archive=zf,
                    mode="w",
                    max_size=max_size,
                )
            else:
                weights_store = H5IOStore(_VARS_FNAME + ".h5", archive=zf, mode="w")
        elif weights_format == "npz":
            weights_store = NpzIOStore(
                _VARS_FNAME + ".npz", archive=zf, mode="w"
            )
        else:
            raise ValueError(
                "Unknown `weights_format` argument. "
                "Expected 'h5' or 'npz'. "
                f"Received: weights_format={weights_format}"
            )

        asset_store = DiskIOStore(_ASSETS_DIRNAME, archive=zf, mode="w")

        _save_state(
            model,
            weights_store=weights_store,
            assets_store=asset_store,
            inner_path="",
            visited_trackables=set(),
        )
        weights_store.close()
        asset_store.close()

    if file_utils.is_remote_path(filepath):
        with file_utils.File(filepath, "wb") as f:
            f.write(zip_filepath.getvalue())


def load_model(filepath, custom_objects=None, compile=True, safe_mode=True):
    """Load a zip archive representing a Keras model."""

    filepath = str(filepath)
    if not filepath.endswith(".keras"):
        raise ValueError(
            "Invalid filename: expected a `.keras` extension. "
            f"Received: filepath={filepath}"
        )

    with file_utils.File(filepath, mode="r+b") as gfile_handle, zipfile.ZipFile(
        gfile_handle, "r"
    ) as zf:
        with zf.open(_CONFIG_FILENAME, "r") as f:
            config_json = f.read()

        # Note: we should NOT use a custom JSON decoder. Anything that
        # needs custom decoding must be handled in deserialize_keras_object.
        config_dict = json.loads(config_json)
        if not compile:
            # Disable compilation
            config_dict["compile_config"] = None
        # Construct the model from the configuration file in the archive.
        with ObjectSharingScope():
            model = deserialize_keras_object(
                config_dict, custom_objects, safe_mode=safe_mode
            )

        all_filenames = zf.namelist()
        if _VARS_FNAME + ".h5" in all_filenames:
            if _VARS_FNAME + ".json" in all_filenames:
                weights_store = ShardedH5IOStore(
                    _VARS_FNAME + ".h5",
                    archive=zf,
                    mode="r",
                )
            else:
                weights_store = H5IOStore(_VARS_FNAME + ".h5", archive=zf, mode="r")
        elif _VARS_FNAME + ".npz" in all_filenames:
            weights_store = NpzIOStore(
                _VARS_FNAME + ".npz", archive=zf, mode="r"
            )
        else:
            raise ValueError(
                f"Expected a {_VARS_FNAME}.h5 or {_VARS_FNAME}.npz file."
            )

        if len(all_filenames) > 3:
            asset_store = DiskIOStore(_ASSETS_DIRNAME, archive=zf, mode="r")
        else:
            asset_store = None

        _load_state(
            model,
            weights_store=weights_store,
            assets_store=asset_store,
            inner_path="",
            visited_trackables=set(),
        )
        weights_store.close()
        if asset_store:
            asset_store.close()
    return model


def save_weights_only(model, filepath, sharded=False, shard_size=None):
    """Save only the weights of a model to a target filepath (.weights.h5).

    Note: only supports h5 for now.
    """
    # TODO: if h5 filepath is remote, create the file in a temporary directory
    # then upload it
    filepath = str(filepath)
    if not filepath.endswith(".weights.h5"):
        raise ValueError(
            "Invalid `filepath` argument: expected a `.weights.h5` extension. "
            f"Received: filepath={filepath}"
        )
    if sharded:
        max_size = shard_size if shard_size is not None else "10GB"
        weights_store = ShardedH5IOStore(filepath, mode="w", max_size=max_size)
    else:
        weights_store = H5IOStore(filepath, mode="w")
    _save_state(
        model,
        weights_store=weights_store,
        assets_store=None,
        inner_path="",
        visited_trackables=set(),
    )
    weights_store.close()


def load_weights_only(model, filepath, sharded=False, skip_mismatch=False):
    """Load the weights of a model from a filepath (.keras or .weights.h5).

    Note: only supports h5 for now.
    """
    temp_dir = None
    archive = None
    filepath = str(filepath)
    if filepath.endswith(".weights.h5"):
        # TODO: download file if h5 filepath is remote
        if sharded:
            weights_store = ShardedH5IOStore(filepath, mode="r")
        else:
            weights_store = H5IOStore(filepath, mode="r")
    elif filepath.endswith(".keras"):
        archive = zipfile.ZipFile(filepath, "r")
        all_filenames = archive.namelist()
        if _VARS_FNAME + ".json" in all_filenames:
            weights_store = ShardedH5IOStore(
                _VARS_FNAME + ".h5",
                archive=archive,
                mode="r",
            )
        else:
            weights_store = H5IOStore(
                _VARS_FNAME + ".h5", archive=archive, mode="r"
            )

    _load_state(
        model,
        weights_store=weights_store,
        assets_store=None,
        inner_path="",
        skip_mismatch=skip_mismatch,
        visited_trackables=set(),
    )
    weights_store.close()
    if temp_dir and file_utils.exists(temp_dir):
        file_utils.rmtree(temp_dir)
    if archive:
        archive.close()


def _write_to_zip_recursively(zipfile_to_save, system_path, zip_path):
    if not file_utils.isdir(system_path):
        zipfile_to_save.write(system_path, zip_path)
    else:
        for file_name in file_utils.listdir(system_path):
            system_file_path = file_utils.join(system_path, file_name).replace(
                "\\", "/"
            )
            zip_file_path = file_utils.join(zip_path, file_name).replace(
                "\\", "/"
            )
            _write_to_zip_recursively(
                zipfile_to_save, system_file_path, zip_file_path
            )


def _walk_trackable(trackable):
    from keras.models import Functional
    from keras.models import Sequential

    if isinstance(trackable, Sequential):
        obj_type = "Sequential"
    elif isinstance(trackable, Functional):
        obj_type = "Functional"
    elif isinstance(trackable, Layer):
        obj_type = "Layer"
    elif isinstance(trackable, Optimizer):
        obj_type = "Optimizer"
    elif isinstance(trackable, Metric):
        obj_type = "Metric"
    elif isinstance(trackable, Loss):
        obj_type = "Loss"
    else:
        raise ValueError(f"Invalid obj_type: {obj_type}")
    attr_skiplist = get_attr_skiplist(obj_type)

    for child_attr in sorted(dir(trackable)):
        if child_attr.startswith("__") or child_attr in attr_skiplist:
            continue
        try:
            child_obj = getattr(trackable, child_attr)
        except Exception:
            # Avoid raising the exception when visiting the attributes.
            continue
        yield child_attr, child_obj


def _save_state(
    trackable,
    weights_store,
    assets_store,
    inner_path,
    visited_trackables,
):
    # If the trackable has already been saved, skip it.
    if id(trackable) in visited_trackables:
        return

    if hasattr(trackable, "save_own_variables") and weights_store:
        trackable.save_own_variables(weights_store.make(inner_path))
    if hasattr(trackable, "save_assets") and assets_store:
        trackable.save_assets(assets_store.make(inner_path))

    visited_trackables.add(id(trackable))

    # Recursively save state of children trackables (layers, optimizers, etc.)
    for child_attr, child_obj in _walk_trackable(trackable):
        if _is_keras_trackable(child_obj):
            _save_state(
                child_obj,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, child_attr).replace(
                    "\\", "/"
                ),
                visited_trackables=visited_trackables,
            )
        elif isinstance(child_obj, (list, dict, tuple, set)):
            _save_container_state(
                child_obj,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, child_attr).replace(
                    "\\", "/"
                ),
                visited_trackables=visited_trackables,
            )


def _load_state(
    trackable,
    weights_store,
    assets_store,
    inner_path,
    skip_mismatch=False,
    visited_trackables=None,
):
    if visited_trackables and id(trackable) in visited_trackables:
        return

    if hasattr(trackable, "load_own_variables") and weights_store:
        if skip_mismatch:
            try:
                trackable.load_own_variables(weights_store.get(inner_path))
            except Exception as e:
                warnings.warn(
                    f"Could not load weights in object {trackable}. "
                    "Skipping object. "
                    f"Exception encountered: {e}",
                    stacklevel=2,
                )
        else:
            trackable.load_own_variables(weights_store.get(inner_path))

    if hasattr(trackable, "load_assets") and assets_store:
        if skip_mismatch:
            try:
                trackable.load_assets(assets_store.get(inner_path))
            except Exception as e:
                warnings.warn(
                    f"Could not load assets in object {trackable}. "
                    "Skipping object. "
                    f"Exception encountered: {e}",
                    stacklevel=2,
                )
        else:
            trackable.load_assets(assets_store.get(inner_path))

    if visited_trackables is not None:
        visited_trackables.add(id(trackable))

    # Recursively load states for Keras trackables such as layers/optimizers.
    for child_attr, child_obj in _walk_trackable(trackable):
        if _is_keras_trackable(child_obj):
            _load_state(
                child_obj,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, child_attr).replace(
                    "\\", "/"
                ),
                skip_mismatch=skip_mismatch,
                visited_trackables=visited_trackables,
            )
        elif isinstance(child_obj, (list, dict, tuple, set)):
            _load_container_state(
                child_obj,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, child_attr).replace(
                    "\\", "/"
                ),
                skip_mismatch=skip_mismatch,
                visited_trackables=visited_trackables,
            )


def _save_container_state(
    container, weights_store, assets_store, inner_path, visited_trackables
):
    used_names = {}
    if isinstance(container, dict):
        container = list(container.values())

    for trackable in container:
        if _is_keras_trackable(trackable):
            # Do NOT address the trackable via `trackable.name`, since
            # names are usually autogenerated and thus not reproducible
            # (i.e. they may vary across two instances of the same model).
            name = naming.to_snake_case(trackable.__class__.__name__)
            if name in used_names:
                used_names[name] += 1
                name = f"{name}_{used_names[name]}"
            else:
                used_names[name] = 0
            _save_state(
                trackable,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, name).replace("\\", "/"),
                visited_trackables=visited_trackables,
            )


def _load_container_state(
    container,
    weights_store,
    assets_store,
    inner_path,
    skip_mismatch,
    visited_trackables,
):
    used_names = {}
    if isinstance(container, dict):
        container = list(container.values())

    for trackable in container:
        if _is_keras_trackable(trackable):
            name = naming.to_snake_case(trackable.__class__.__name__)
            if name in used_names:
                used_names[name] += 1
                name = f"{name}_{used_names[name]}"
            else:
                used_names[name] = 0
            _load_state(
                trackable,
                weights_store,
                assets_store,
                inner_path=file_utils.join(inner_path, name).replace("\\", "/"),
                skip_mismatch=skip_mismatch,
                visited_trackables=visited_trackables,
            )


class DiskIOStore:
    """Asset store backed by disk storage.

    If `archive` is specified, then `root_path` refers to the filename
    inside the archive.

    If `archive` is not specified, then `root_path` refers to the full path of
    the target directory.
    """

    def __init__(self, root_path, archive=None, mode=None):
        self.mode = mode
        self.root_path = root_path
        self.archive = archive
        self.tmp_dir = None
        if self.archive:
            self.tmp_dir = get_temp_dir()
            if self.mode == "r":
                self.archive.extractall(path=self.tmp_dir)
            self.working_dir = file_utils.join(
                self.tmp_dir, self.root_path
            ).replace("\\", "/")
            if self.mode == "w":
                file_utils.makedirs(self.working_dir)
        else:
            if mode == "r":
                self.working_dir = root_path
            else:
                self.tmp_dir = get_temp_dir()
                self.working_dir = file_utils.join(
                    self.tmp_dir, self.root_path
                ).replace("\\", "/")
                file_utils.makedirs(self.working_dir)

    def make(self, path):
        if not path:
            return self.working_dir
        path = file_utils.join(self.working_dir, path).replace("\\", "/")
        if not file_utils.exists(path):
            file_utils.makedirs(path)
        return path

    def get(self, path):
        if not path:
            return self.working_dir
        path = file_utils.join(self.working_dir, path).replace("\\", "/")
        if file_utils.exists(path):
            return path
        return None

    def close(self):
        if self.mode == "w" and self.archive:
            _write_to_zip_recursively(
                self.archive, self.working_dir, self.root_path
            )
        if self.tmp_dir and file_utils.exists(self.tmp_dir):
            file_utils.rmtree(self.tmp_dir)


class H5IOStore:
    def __init__(self, root_path, archive=None, mode="r"):
        """Numerical variable store backed by HDF5.

        If `archive` is specified, then `root_path` refers to the filename
        inside the archive.

        If `archive` is not specified, then `root_path` refers to the path of
        the h5 file on disk.
        """
        self.root_path = root_path
        self.mode = mode
        self.archive = archive
        self.io_file = None

        if self.archive:
            if self.mode == "w":
                self.io_file = io.BytesIO()
            else:
                self.io_file = self.archive.open(self.root_path, "r")
            self.h5_file = h5py.File(self.io_file, mode=self.mode)
        else:
            self.h5_file = h5py.File(root_path, mode=self.mode)

    def make(self, path):
        if not path:
            return self.h5_file.create_group("vars")
        return self.h5_file.create_group(path).create_group("vars")

    def get(self, path):
        if not path:
            return self.h5_file["vars"]
        if path in self.h5_file and "vars" in self.h5_file[path]:
            return self.h5_file[path]["vars"]
        return {}

    def close(self):
        self.h5_file.close()
        if self.mode == "w" and self.archive:
            self.archive.writestr(self.root_path, self.io_file.getvalue())
        if self.io_file:
            self.io_file.close()


class ShardedH5IOStore:
    def __init__(self, root_path, max_size="10GB", archive=None, mode="r"):
        self.shard_list = []
        self.root_path = root_path
        self.mode = mode
        self.archive = archive
        self.io_file = None
        self.max_size = convert_str_bytes_to_int(max_size)
        self.current_shard_size = 0

        self.var_shard_map_filename = str(root_path).replace(".weights.h5", ".weights.json")
        if not os.path.exists(self.var_shard_map_filename):
            if self.mode == "w":
                self.var_shard_map = {}
            if self.mode =="r":
                raise FileNotFoundError(
                    f"Loading a sharded `.weights.h5` file requires "
                    "its corresponding sharding map JSON file "
                    f"{self.var_shard_map_filename} in the same directory. "
                    "Please ensure all weights files and the sharding map JSON file "
                    "are in the same directory when loading a sharded weights file."
                )
        else:
            with open(self.var_shard_map_filename, "r") as map_file:
                self.var_shard_map = json.load(map_file)

        self.h5_file = self._create_new_file(root_path)

    def _create_new_file(self, path):
        if path in self.shard_list:
            path = resolve_duplicate_filename(str(path), self.shard_list)
            self.root_path = path
        if self.archive:
            if self.mode == "w":
                self.io_file = io.BytesIO()
            else:
                self.io_file = self.archive.open(path, "r")
            return h5py.File(self.io_file, mode=self.mode)
        else:
            return h5py.File(path, mode=self.mode)

    def _change_access_file(self, filename):  # Read-only
        self.close()
        if self.archive:
            self.io_file = self.archive.open(filename, "r")
            return h5py.File(self.io_file, mode=self.mode)
        else:
            return h5py.File(filename, mode=self.mode)

    def make(self, path):
        def _get_size(key):
            if isinstance(self.h5_file[key], h5py.Dataset):
                self.current_shard_size += self.h5_file[key].nbytes

        self.current_shard_size = 0
        self.h5_file.visit(_get_size)
        if self.current_shard_size > self.max_size:
            self.shard_list.append(self.h5_file.filename)
            self.close()
            self.h5_file = self._create_new_file(self.root_path)
        if not path:
            group = self.h5_file.create_group("vars")
        else:
            group = self.h5_file.create_group(path).create_group("vars")
        self.var_shard_map[group.name] = self.root_path
        return group

    def get(self, path):
        if not path:
            return self.h5_file["vars"]
        if path in self.h5_file and "vars" in self.h5_file[path]:
            return self.h5_file[path]["vars"]

        # If not found, check shard map and switch files
        filename = self.var_shard_map.get(path) or self.var_shard_map.get("/" + path +"/vars")
        if filename is not None and self.h5_file.name != filename:
            new_file = self._change_access_file(filename)
            if "vars" in new_file[path]:
                self.h5_file = new_file
                return self.h5_file[path]["vars"]
        return {}

    def close(self):
        self.h5_file.close()
        if self.mode == "w":
            with open(self.var_shard_map_filename, "w") as map_file:
                map_file.write(json.dumps(self.var_shard_map))
            if self.archive:
                self.archive.writestr(self.root_path, self.io_file.getvalue())
        if self.io_file:
            self.io_file.close()



def convert_str_bytes_to_int(size):
    if size.upper().endswith("GB"):
        return int(size[:-2]) * (10**9)
    if size.upper().endswith("MB"):
        return int(size[:-2]) * (10**6)
    if size.upper().endswith("KB"):
        return int(size[:-2]) * (10**3)
    raise ValueError(
        "Invalid format for `size`. Use an integer followed by the unit "
        "(GB, MB, or KB). For example, '5GB' or '15MB'."
    )


def resolve_duplicate_filename(path, path_list):
    pattern = re.compile("_\d\.weights\.h5")
    pre_duplicate = pattern.split(path)[0]  # Check for pre-existing duplicate
    if not pre_duplicate.endswith(".weights.h5"):
        match_list = list(filter(lambda x: x.startswith(pre_duplicate), path_list))
        if len(match_list) > 1:
            return pre_duplicate + "_" + str(len(match_list)) + ".weights.h5"
    return path.replace(".weights.h5", "_1.weights.h5")


def dtype_to_bytes(dtype):
    if "bool" in str(dtype):
        return 1 / 8
    bits = re.search(r"[^\d](\d+)$", str(dtype))
    if bits is None:
        raise ValueError(f"`dtype` is not a valid dtype: {dtype}.")
    return int(bits.groups()[0]) // 8  # Bit size in bytes


class NpzIOStore:
    def __init__(self, root_path, archive=None, mode="r"):
        """Numerical variable store backed by NumPy.savez/load.

         If `archive` is specified, then `root_path` refers to the filename
        inside the archive.

        If `archive` is not specified, then `root_path` refers to the path of
        the npz file on disk.
        """
        self.root_path = root_path
        self.mode = mode
        self.archive = archive
        if mode == "w":
            self.contents = {}
        else:
            if self.archive:
                self.f = archive.open(root_path, mode="r")
            else:
                self.f = open(root_path, mode="rb")
            self.contents = np.load(self.f, allow_pickle=True)

    def make(self, path):
        if not path:
            self.contents["__root__"] = {}
            return self.contents["__root__"]
        self.contents[path] = {}
        return self.contents[path]

    def get(self, path):
        if not path:
            if "__root__" in self.contents:
                return dict(self.contents["__root__"])
            return {}
        if path in self.contents:
            return self.contents[path].tolist()
        return {}

    def close(self):
        if self.mode == "w":
            if self.archive:
                self.f = self.archive.open(
                    self.root_path, mode="w", force_zip64=True
                )
            else:
                self.f = open(self.root_path, mode="wb")
            np.savez(self.f, **self.contents)
        self.f.close()


def get_temp_dir():
    temp_dir = tempfile.mkdtemp()
    testfile = tempfile.TemporaryFile(dir=temp_dir)
    testfile.close()
    return temp_dir


def get_attr_skiplist(obj_type):
    skiplist = global_state.get_global_attribute(
        f"saving_attr_skiplist_{obj_type}", None
    )
    if skiplist is not None:
        return skiplist

    skiplist = [
        "_self_unconditional_dependency_names",
    ]
    if obj_type == "Layer":
        ref_obj = Layer()
        skiplist += dir(ref_obj)
    elif obj_type == "Functional":
        ref_obj = Layer()
        skiplist += dir(ref_obj) + ["operations", "_operations"]
    elif obj_type == "Sequential":
        ref_obj = Layer()
        skiplist += dir(ref_obj) + ["_functional"]
    elif obj_type == "Metric":
        ref_obj_a = Metric()
        ref_obj_b = CompileMetrics([], [])
        skiplist += dir(ref_obj_a) + dir(ref_obj_b)
    elif obj_type == "Optimizer":
        ref_obj = Optimizer(1.0)
        skiplist += dir(ref_obj)
        skiplist.remove("variables")
    elif obj_type == "Loss":
        ref_obj = Loss()
        skiplist += dir(ref_obj)
    else:
        raise ValueError(f"Invalid obj_type: {obj_type}")
    global_state.set_global_attribute(
        f"saving_attr_skiplist_{obj_type}", skiplist
    )
    return skiplist


def _is_keras_trackable(obj):
    return isinstance(
        obj,
        (
            Layer,
            Optimizer,
            Metric,
            Loss,
        ),
    )
