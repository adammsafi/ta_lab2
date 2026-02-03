from setuptools import setup, find_packages

setup(
    name="fedtools2",
    version="0.1.0",
    description="ETL + utilities for Federal Reserve rate datasets",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={"fedtools2": ["config/*.yaml"]},
    install_requires=[
        "pandas>=2.2",
        "numpy>=1.26",
        "pyyaml>=6.0",
        "matplotlib>=3.8",
        "sqlalchemy>=2.0",
    ],
    entry_points={"console_scripts": ["fedtools2=fedtools2.etl:main"]},
)
