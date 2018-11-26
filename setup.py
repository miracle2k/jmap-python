# !/usr/bin/env python

from setuptools import setup, find_packages

setup(
    name='jmap-python',
    packages=find_packages(),
    install_requires=[
      'marshmallow>=3.0.0b19'
    ],
    version='0.1.0',
    description='JMAP library for Python',
    author='Michael Elsdorfer',
    license='BSD',
    author_email='michael@elsdorfer.com',
    url='https://github.com/miracle2k/jmap-python',
    keywords=['email', 'jmap'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Topic :: Software Development',
    ],
)