python3 -c "
import sqlite3
conn = sqlite3.connect('data/aisdb.sqlite')
print('AIS:', conn.execute('SELECT COUNT(*) FROM ais_messages').fetchone())
print('own_position:', conn.execute('SELECT COUNT(*) FROM own_position').fetchone())
"