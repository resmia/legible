import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: legible <url>")
        return

    url = sys.argv[1]
    print(f"Legible received: {url}")


if __name__ == "__main__":
    main()