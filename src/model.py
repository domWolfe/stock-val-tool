from .get_ticker_list import generate_ticker_file

def begin():
    try:
        tickers = generate_ticker_file()
        print(f"Generated ticker list with {len(tickers)} entries. Sample:")
        print(tickers[:10])
    except ValueError as e:
        print(e)