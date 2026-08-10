"""Streamlit entry point kept outside the package to avoid stdlib name shadowing."""

from macro_nowcast.dashboard import main

if __name__ == "__main__":
    main()
