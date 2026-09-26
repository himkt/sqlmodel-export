import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Export model metadata as offline creation DDL")
    parser.add_argument("target", metavar="TARGET")
    parser.add_argument("--dialect", required=True, choices=("postgresql", "sqlite", "mysql"))
    parser.add_argument("--output", metavar="PATH")
    parser.parse_args()
    raise NotImplementedError("DDL generation and delivery require implementation")
