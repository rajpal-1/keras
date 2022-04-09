


"""Keras audio dataset loading utilities.""" 

import tensorflow.compat.v2 as tf
# pylint: disable=g-classes-have-attributes

import numpy as np
from keras.utils import dataset_utils
from tensorflow.python.util.tf_export import keras_export

ALLOWED_FORMATS = ('.wav',)



@keras_export('keras.utils.audio_dataset_from_directory',
              'keras.preprocessing.audio_dataset_from_directory',
              v1=[])
def audio_dataset_from_directory(directory,
    labels="inferred", 
    label_mode="int", 
    class_names=None, 
    batch_size=32, 
    sampling_rate=None, 
    output_sequence_length=None, 
    ragged=False, 
    shuffle=True, 
    seed=None, 
    validation_split=None, 
    subset=None, 
    follow_links=False):

    """Generates a `tf.data.Dataset` from audio files in a directory.

    If your directory structure is:

    ```
    main_directory/
    ...class_a/
    ......a_audio_1.wav
    ......a_audio_2.wav
    ...class_b/
    ......b_audio_1.wav
    ......b_audio_2.wav
    ```

    Then calling `audio_dataset_from_directory(main_directory, labels='inferred')`
    will return a `tf.data.Dataset` that yields batches of audio files from
    the subdirectories `class_a` and `class_b`, together with labels
    0 and 1 (0 corresponding to `class_a` and 1 corresponding to `class_b`).

    Only `.wav` files are supported at this time.

    Args:
      directory: Directory where the data is located.
          If `labels` is "inferred", it should contain
          subdirectories, each containing audio files for a class.
          Otherwise, the directory structure is ignored.
      labels: Either "inferred"
          (labels are generated from the directory structure),
          None (no labels),
          or a list/tuple of integer labels of the same size as the number of
          audio files found in the directory. Labels should be sorted according
          to the alphanumeric order of the audio file paths
          (obtained via `os.walk(directory)` in Python).
      label_mode: String describing the encoding of `labels`. Options are:
          - 'int': means that the labels are encoded as integers
              (e.g. for `sparse_categorical_crossentropy` loss).
          - 'categorical' means that the labels are
              encoded as a categorical vector
              (e.g. for `categorical_crossentropy` loss).
          - 'binary' means that the labels (there can be only 2)
              are encoded as `float32` scalars with values 0 or 1
              (e.g. for `binary_crossentropy`).
          - None (no labels).
      class_names: Only valid if "labels" is "inferred". This is the explicit
          list of class names (must match names of subdirectories). Used
          to control the order of the classes
          (otherwise alphanumerical order is used).
      batch_size: Size of the batches of data. Default: 32.
        If `None`, the data will not be batched
        (the dataset will yield individual samples).
      sampling_rate: Number of samples taken each second.
      output_sequence_length: Maximum length of a audio sequence. audio files longer than this will 
      be truncated to `output_sequence_length`
      shuffle: Whether to shuffle the data. Default: True.
          If set to False, sorts the data in alphanumeric order.
      seed: Optional random seed for shuffling and transformations.
      validation_split: Optional float between 0 and 1,
          fraction of data to reserve for validation.
      subset: Subset of the data to return.
          One of "training" or "validation".
          Only used if `validation_split` is set.
      follow_links: Whether to visits subdirectories pointed to by symlinks.
          Defaults to False.

    Returns:
      A `tf.data.Dataset` object.
        - If `label_mode` is None, it yields `string` tensors of shape
          `(batch_size,)`, containing the contents of a batch of audio files.
        - Otherwise, it yields a tuple `(audio, labels)`, where `audio`
          has shape `(batch_size, sequence_length, num_channels)` and `labels` follows the format described
          below.

    Rules regarding labels format:
      - if `label_mode` is `int`, the labels are an `int32` tensor of shape
        `(batch_size,)`.
      - if `label_mode` is `binary`, the labels are a `float32` tensor of
        1s and 0s of shape `(batch_size, 1)`.
      - if `label_mode` is `categorical`, the labels are a `float32` tensor
        of shape `(batch_size, num_classes)`, representing a one-hot
        encoding of the class index.
    """


    if labels not in ('inferred', None):
        if not isinstance(labels, (list, tuple)):
            raise ValueError(
                '`labels` argument should be a list/tuple of integer labels, of '
                'the same size as the number of audio files in the target '
                'directory. If you wish to infer the labels from the subdirectory '
                'names in the target directory, pass `labels="inferred"`. '
                'If you wish to get a dataset that only contains audio samples '
                f'(no labels), pass `labels=None`. Received: labels={labels}')
        if class_names:
            raise ValueError('You can only pass `class_names` if '
                        f'`labels="inferred"`. Received: labels={labels}, and '
                        f'class_names={class_names}')
    if label_mode not in {'int', 'categorical', 'binary', None}:
        raise ValueError('`label_mode` argument must be one of "int", "categorical", "binary", 'f'or None. Received: label_mode={label_mode}')
    


    if not ragged and output_sequence_length is None:
        raise Exception(f'The dataset should be ragged dataset or fixed sequence length dataset, found ragged={ragged} and output_sequence_length={output_sequence_length}')
    elif ragged and output_sequence_length is not None:
        raise Exception('Cannot set both `ragged` and `output_sequence_length`')
    


    if labels is None or label_mode is None:
        labels = None
        label_mode = None

    dataset_utils.check_validation_split_arg(validation_split, subset, shuffle, seed)

    if seed is None:
        seed = np.random.randint(1e6)
        
    file_paths, labels, class_names = dataset_utils.index_directory(directory, labels, formats=ALLOWED_FORMATS, class_names=class_names, 
        shuffle=shuffle, 
        seed=seed, 
        follow_links=follow_links)

    if label_mode == 'binary' and len(class_names) != 2:
        raise ValueError(f'When passing `label_mode="binary"`, there must be exactly 2 'f'class_names. Received: class_names={class_names}')

    file_paths, labels = dataset_utils.get_training_or_validation_split(file_paths, labels, validation_split, subset)
    if not file_paths:
        raise ValueError(f'No audio files found in directory {directory}. 'f'Allowed format(s): {ALLOWED_FORMATS}')


    if ragged:
        dataset = paths_and_labels_to_ragged_dataset(file_paths=file_paths, labels=labels, 
            label_mode=label_mode, 
            num_classes=len(class_names), 
            sampling_rate=sampling_rate)
    else:
        dataset = paths_and_labels_to_dataset(file_paths=file_paths, labels=labels, label_mode=label_mode, 
            num_classes=len(class_names), 
            sampling_rate=sampling_rate, 
            output_sequence_length=output_sequence_length)

    dataset = dataset.prefetch(tf.data.AUTOTUNE)
    if batch_size is not None:
        if shuffle:
            dataset = dataset.shuffle(buffer_size=batch_size * 8, seed=seed)
        dataset = dataset.batch(batch_size)
    else:
        if shuffle:
            dataset = dataset.shuffle(buffer_size=1024, seed=seed)

    # Users may need to reference `class_names`.
    dataset.class_names = class_names
    return dataset


def prepare_audio(path, sampling_rate, output_sequence_length=-1):
    """Reads and prepare the audio file."""
    audio = tf.io.read_file(path)
    audio, _ = tf.audio.decode_wav(contents=audio, desired_samples=output_sequence_length )
    if sampling_rate is not None:
        audio = tf.audio.encode_wav(audio, sampling_rate)
        audio, _ = tf.audio.decode_wav(audio)
    return audio

def paths_and_labels_to_dataset(file_paths,
                                labels,
                                label_mode,
                                num_classes, sampling_rate, output_sequence_length):
  """Constructs a fixed size dataset of audio and labels."""
  path_ds = tf.data.Dataset.from_tensor_slices(file_paths)
  audio_ds = path_ds.map(lambda x: prepare_audio(x, sampling_rate, output_sequence_length), num_parallel_calls=tf.data.AUTOTUNE)
  if label_mode:
    label_ds = dataset_utils.labels_to_dataset(labels, label_mode, num_classes)
    audio_ds = tf.data.Dataset.zip((audio_ds, label_ds))
  return audio_ds

def paths_and_labels_to_ragged_dataset(file_paths, labels, label_mode, num_classes, sampling_rate):
    """Constructs a ragged dataset of audio and labels."""
    audio_ds = tf.data.Dataset.from_tensor_slices(file_paths)
    audio_ds = audio_ds.map(lambda x: prepare_audio(x, sampling_rate), num_parallel_calls=tf.data.AUTOTUNE)
    audio_ds = audio_ds.map(lambda x: tf.RaggedTensor.from_tensor(x), num_parallel_calls=tf.data.AUTOTUNE)
    if label_mode:
        label_ds = dataset_utils.labels_to_dataset(labels, label_mode, num_classes)
        audio_ds = tf.data.Dataset.zip((audio_ds, label_ds))
    return audio_ds
