from hsbcpdfscraper import accountstatement
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger('hsbcstatement').setLevel(logging.DEBUG)

st = accountstatement.Statement(".\\working\\mypdffile.pdf")
st.process()

json = st.get_json()
df = st.get_df()

print(json)