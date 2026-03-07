import sys

try:
    from image_detector import detect_fake_text
except Exception:
    detect_fake_text = None


def main():
    if detect_fake_text is None:
        print("Text detector not available. Ensure image_detector.py defines detect_fake_text and required config.")
        sys.exit(1)

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:]).strip()
    else:
        try:
            text = input("Enter text to analyze: ").strip()
        except EOFError:
            text = ""

    if not text:
        print("No text provided. Exiting.")
        sys.exit(1)

    try:
        result = detect_fake_text(text)
    except Exception as e:
        result = f"Detection error: {e}"

    print("=== Analysis ===")
    print(result)


if __name__ == "__main__":
    main()
