import datetime
import requests
import json
import MySQLdb as mdb
from collections import defaultdict
from datetime import datetime, timedelta
from warnings import filterwarnings

# ignore truncation warnings
filterwarnings('ignore', category=mdb.Warning)

def parse_date_str(date_str):
    """
    Attempts to coerce datestr (of preferined formats) to datetime
    """
    date_formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
                    "%m-%d-%Y", "%m/%d/%Y", "%m.%d.%Y", "%m%d%Y",
                    "%d-%m-%y", "%d/%m/%y", "%d.%m.%y", "%d%m%Y"]
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    raise ValueError("couldn't parse dates, please use -h for accepted formats")



def get_ids_and_tickers(conn):
    """
    Retrieves list of ids and corresponding ticker for all symbols in the
    symbol table.

    Returns:
        list: [(id, ticker) for every ticker found in the database]
    """

    cur = conn.cursor()
    cur.execute('SELECT id, ticker FROM symbol')
    rows = cur.fetchall()
    cur.close()
    return [(row[0], row[1]) for row in rows]


def _get_single_stock(ticker, start, end):
    """
    Retrieve daily hisotircal OHLC data from Yahoo Finance API

    Parameters:
        ticker (str) : Ticker you want historical data for
        start  (datetime) : (YYYY, MM, DD)
        end    (datetime) : (YYYY, MM, DD)

    Returns:
        List[tuple]:
            [ (Date, Open, High, Low, Close, Volume, AdjClose) ...]
    """
    start, end = start.timetuple()[:3], end.timetuple()[:3]
    YFINANCE_CSV_URL = ('http://ichart.finance.yahoo.com/table.csv?'
                       's=%s&a=%s&b=%s&c=%s&d=%s&e=%s&f=%s')
    req_url = YFINANCE_CSV_URL % (ticker, start[1]-1, start[2], start[0],
                                  end[1]-1, end[2], end[0])
    try:
        resp = requests.get(req_url)
        resp.raise_for_status()

        yahoo_data_iter = iter(resp.iter_lines())
        next(yahoo_data_iter) # ignore header
        daily_prices = []

        for day in yahoo_data_iter:
            row = day.decode('utf-8').split(',')
            daily_prices.append( (datetime.strptime(row[0], '%Y-%m-%d'),
                                  row[1], row[2], row[3], row[4], row[5], row[6]))
    except requests.exceptions.RequestException as e:
        print(e)
        return

    return daily_prices


def _get_many_stocks(tickers, start, end):
    """
    Queryies every ticker in tickers at the same time. Used to avoid hitting the API cap.

    Parameters:
        tickers (list[str]) : List of tickers to get historical data for
        start (datetime) : (YYYY, MM, DD)
        end   (datetime) : (YYYY, MM, DD)
    """
    tickers = '(' + ','.join(['\"' + s.upper() + '"' for s in tickers]) + ')'
    start, end = datetime.strftime(start, '%Y-%m-%d') , datetime.strftime(end, '%Y-%m-%d')
    query = ('select * '
             'from yahoo.finance.historicaldata '
             'where symbol IN {t} AND '
             'startDate="{s}" AND endDate="{e}"'.format(t=tickers, s=start, e=end))

    payload = {
        'q': query, 'format': 'json', 'env': 'store://datatables.org/alltableswithkeys'}
    # make API Call and convert to JSON obj
    try:
        resp = requests.get('http://query.yahooapis.com/v1/public/yql?',
                            params=payload)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(e)
    try:
        json_data = json.loads(resp.text)["query"]["results"]["quote"]
    except TypeError:
        print("YahooFinance query returned nothing")
        return

    # coerce JSON object to rows, to be used in _insert_single_daily_stock
    ticker_to_rows = defaultdict(list)
    for obj in json_data:
        date = datetime.strptime(obj['Date'], '%Y-%m-%d')
        row = (date, obj['Open'], obj['High'], obj['Low'], obj['Close'],
               obj['Volume'], obj['Adj_Close'])
        ticker_to_rows[obj['Symbol']].append(row)

    return ticker_to_rows


def _insert_single_daily_stock(conn, data_vendor_id, symbol_id, daily_data):
    """
    Inserts single historical stock into database

    Parameters:
        date_vendor_id (int) : Id to uniquely identify the vendor of stock data
        symbol_id (int) : Id of the stock (foreign key to symbol table)
        daily_data (list) : The rows of data returned from `get_daily_yahoo_historical`
    """
    now = datetime.utcnow()
    # add data vendor and symbol id to data
    daily_prices = [(data_vendor_id, symbol_id, t[0], now, now, *t[1:]) for t in daily_data]
    columns = ("data_vendor_id, symbol_id, price_date, created_date, last_updated_date,"
               "open_price, high_price, low_price, close_price, volume, adj_close_price")
    fill_str = ("%s, " * 11)[:-2]
    template_insert_str = ("INSERT IGNORE INTO daily_price ({columns}) "
                          "VALUES ({vals})".format(columns=columns, vals=fill_str))

    cur = conn.cursor()
    cur.executemany(template_insert_str, daily_prices)
    cur.close()


def insert_daily_snp500(conn, start=None, end=None):
    """
    Inserts daily historical OHLC data for each company found in the symbol
    table. This will call different Yahoo Finance endpoints depending on the
    range [start, end]

    Parameters:
        start (str) : YYYYMMDD, MMDDYYYY, DDMMYYYY
        end   (str) : YYYYMMDD, MMDDYYYY, DDMMYYYY
        * either format can also use '/', '-', '.' between tokens
    """

    # convert date strs to tuple (YYYY, MM, DD)

    if start is None:
        start = datetime.now() - timedelta(days=30)
    else:
        start = parse_date_str(start)

    if end is None:
        end = datetime.now()
    else:
        end = parse_date_str(end)

    dist = (end - start)
    print("Inserting daily S&P 500 price data from",
          datetime.strftime(start, '%Y-%m-%d'), "to",
          datetime.strftime(end, '%Y-%m-%d'), sep=' ')
    if dist.days <= 0:
        print("`daily_price` already up-to-date")
        return
    elif dist.days <= 30:
        tickers = [ ticker for _, ticker in get_ids_and_tickers(conn) ]
        data = _get_many_stocks(tickers, start, end)
        if data is None:
            return
        ticker_to_id = {ticker:id for id, ticker in get_ids_and_tickers(conn) }
        for ticker in data:
            id = ticker_to_id[ticker]
            _insert_single_daily_stock(conn, '1', id, data[ticker])
    else:
        for id, ticker in get_ids_and_tickers(conn):
            print("Adding data for {0}".format(ticker))
            daily_data = _get_single_stock(ticker, start, end)
            _insert_single_daily_stock(conn, '1', id, daily_data)

