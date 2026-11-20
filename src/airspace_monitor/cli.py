"""Command-line entry point; data collection will be added next."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live Airspace Monitor for Hungary (project scaffold)."
    )
    parser.parse_args()
    print("Project scaffold ready. Data collection and the web application are not implemented yet.")
