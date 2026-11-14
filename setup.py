from glob import glob
from setuptools import setup

setup(
    name='mara', version='1.0.0',
    description='User-scoped, evidence-preserving investment deliberation',
    python_requires='>=3.9', packages=['mara'],
    entry_points={'console_scripts':['mara=mara.cli:main']},
    data_files=[('share/mara/guides/roles',glob('guides/roles/*.md')),
                ('share/mara/guides/personas',glob('guides/personas/*.md'))],
)
