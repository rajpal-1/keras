# -*- coding: utf-8 -*-
import inspect
import keras_autodoc
import pathlib
import re
import shutil

from docs.structure import EXCLUDE
from docs.structure import PAGES
from docs.structure import template_hidden_np_implementation
from docs.structure import template_np_implementation
from keras.backend import numpy_backend

keras_dir = pathlib.Path(__file__).resolve().parents[1]


def post_process_signature(signature):
    parts = re.split(r'\.(?!\d)', signature)
    if len(parts) >= 4:
        if parts[1] == 'layers':
            signature = 'keras.layers.' + '.'.join(parts[3:])
        if parts[1] == 'utils':
            signature = 'keras.utils.' + '.'.join(parts[3:])
        if parts[1] == 'backend':
            signature = 'keras.backend.' + '.'.join(parts[3:])
    return signature


def clean_module_name(name):
    if name.startswith('keras_applications'):
        name = name.replace('keras_applications', 'keras.applications')
    if name.startswith('keras_preprocessing'):
        name = name.replace('keras_preprocessing', 'keras.preprocessing')
    return name


def add_np_implementation(function, docstring):
    np_implementation = getattr(numpy_backend, function.__name__)
    code = inspect.getsource(np_implementation)
    code_lines = code.split('\n')
    for i in range(len(code_lines)):
        if code_lines[i]:
            # if there is something on the line, add 8 spaces.
            code_lines[i] = '        ' + code_lines[i]
    code = '\n'.join(code_lines[:-1])

    if len(code_lines) < 10:
        section = template_np_implementation.replace('{{code}}', code)
    else:
        section = template_hidden_np_implementation.replace('{{code}}', code)
    return docstring.replace('{{np_implementation}}', section)


def preprocess_docstring(docstring, function, signature):
    if 'backend' in signature and '{{np_implementation}}' in docstring:
        docstring = add_np_implementation(function, docstring)
    return docstring


def generate(dest_dir):
    template_dir = keras_dir / 'docs' / 'templates'
    keras_autodoc.generate(
        dest_dir,
        template_dir,
        PAGES,
        'https://github.com/keras-team/keras/blob/master',
        keras_dir / 'examples',
        EXCLUDE,
        clean_module_name=clean_module_name,
        post_process_signature=post_process_signature,
        preprocess_docstring=preprocess_docstring,
    )
    readme = (keras_dir / 'README.md').read_text()
    index = (template_dir / 'index.md').read_text()
    index = index.replace('{{autogenerated}}', readme[readme.find('##'):])
    (dest_dir / 'index.md').write_text(index, encoding='utf-8')
    shutil.copyfile(keras_dir / 'CONTRIBUTING.md', dest_dir / 'contributing.md')


if __name__ == '__main__':
    generate(keras_dir / 'docs' / 'sources')
