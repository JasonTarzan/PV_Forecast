from setuptools import setup,find_packages

import sys


install_requires = [
    'forecastiopy==0.22',
    'pvlib==0.5.1',
    'pandas==0.22.0'
]

setup(name='forecast',
      version='0.0.1',
      packages=find_packages(),
      include_package_data=True,
      entry_points={
          "console_scripts": [
              "forecast = forecast.main:run",
          ]
      },
      install_requires=install_requires,
)
