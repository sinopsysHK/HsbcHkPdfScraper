import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="hsbcpdf-sinopsys",
    version="0.1.0",
    author="SinopsysHK",
    author_email="sinofwd@gmail.com",
    description="An HSBC Hk Statement PDF extractor",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/sinopsysHK/HsbcHkPdfScraper",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)