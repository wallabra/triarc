import os
import setuptools


setuptools.setup(
    name="triarc",
    version="0.1.2-1",
    author="Gustavo Ramos Rehermann",
    author_email="rehermann6046@gmail.com",
    license='COIL',
    description="A trio library for automating responses to commands (bots) and the like. Ships with an IRC backend.",
    keywords='bot network async trio irc',

    long_description=open(os.path.join(os.path.dirname(__file__), 'README.md')).read(),
    packages=['triarc', 'triarc.backends', 'triarc.mutators'],
    classifiers=[
        'Framework :: Trio',
        'Topic :: System :: Networking',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Communications'
    ]
)