from setuptools import setup
from setuptools import find_packages


setup(name='Keras',
      version='2.0.7',
      description='Deep Learning for Python',
      author='Francois Chollet',
      author_email='francois.chollet@gmail.com',
      url='https://github.com/fchollet/keras',
      download_url='https://github.com/fchollet/keras/tarball/2.0.7',
      license='MIT',
      install_requires=['theano', 'pyyaml', 'six'],
      extras_require={
          'h5py': ['h5py'],
          'visualize': ['pydot>=1.2.0'],
          'tests': ['pytest',
                    'pytest-pep8',
                    'pytest-xdist',
                    'pytest-cov'],
      },
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'Intended Audience :: Developers',
          'Intended Audience :: Education',
          'Intended Audience :: Science/Research',
          'License :: OSI Approved :: MIT License',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.6',
          'Topic :: Software Development :: Libraries',
          'Topic :: Software Development :: Libraries :: Python Modules'
      ],
      packages=find_packages())
