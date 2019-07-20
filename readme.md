# HsbcStatementHKScraper
Simple quick and dirty python3 based HSBC Account statement (for Hong Kong) PDF scrapper.

At least working on my 4 last years own statements without errors

### Usage

from command line
```sh
$ python HsbcStatementHKScraper <pdf file path> <outputdir>
```
write a csv file in <outputdir> with file name pattern [account number]-[statement date yyymm].csv

can also be used from code
```python
from HsbcAccStatementHKScraper import Statement

st = Statement(".\\working\\mypdffile.pdf")
st.process()

json = st.get_json()
df = st.get_df()
```

returns json file with following structure:
```json
{
    "main_account": "XXX-YYYYYY-ZZZ",
    "statement_date": "25/05/2019",
    "previous_balance": {
        "HKDSavings": {
            "HKD": 50000000.00
        }, 
        "HKDCurrent": {
            "HKD": 69000000.00
        }, 
        "FCYSavings": {
            "USD": 32000000.00, 
            "EUR": 57000000.00
        }
    }, 
    "entries": [
        {
            "account": "HKDSavings",
            "date": "27/04/2019",
            "description": "MONTHLY EARNINGS", 
            "currency": "HKD", 
            "amount": 1000000.00
        }, 
        ...
    ]
}
```

### Dependencies

* [pdfquery] (thus pdfminer) - to locate relevant areas in the PDF
* [camelot] (thus panda) - to extract the data tables

# New Features!

  - working



### Installation

requires [python](https://www.python.org/) v3.7 to run (other versions not tested).

Install the dependencies.

```sh
$ pip install pdfquery
$ pip install camelot
```

Packages are also available with conda (but my env is messed up so didn't managed to accomodate with version conflicts)

Then copy source code from [github]()

### Todos

 - Write (MORE) Tests
 - Add support for Credit Card Statement

License
----

GNU/MIT/FREE/...


**Free Software, Hell Yeah!**

[//]: # (These are reference links used in the body of this note and get stripped out when the markdown processor does its job. There is no need to format nicely because it shouldn't be seen. Thanks SO - http://stackoverflow.com/questions/4823468/store-comments-in-markdown-syntax)

   [pdfquery]: <https://github.com/jcushman/pdfquery>
   [camelot]: <https://camelot-py.readthedocs.io/en/master/index.html>
