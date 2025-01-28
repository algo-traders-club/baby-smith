from setuptools import setup, find_packages

setup(
    name="agent_smith",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "hyperliquid",
        "streamlit",
        "plotly",
        "pandas",
        "loguru",
        "python-dotenv",
        "rich",
        "pydantic",
        "eth_account"
    ],
)