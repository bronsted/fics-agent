#!/usr/bin/env python3
import logging
import signal
import time
import getpass
import telnetlib
import sys
import re 
import sqlite3

class Player:
	"""A representation of a fics player (as returned by the 'who' command)"""

	STATUSES = {
		'^' : 'INGAME', 
		'~' : 'SIMUL_MATCH', 
		':' : 'NOT_OPEN', 
		'#' : 'EXAMINING',
		'.' : 'INACTIVE',
		'&' : 'INTOURNAMENT'}
	
	def __init__(self, rating, status, name):
		self.rating = rating
		self.status = self.STATUSES[status]
		self.name = name

	def __repr__(self):
		return "(" + self.rating + ", " + self.status + ", " + self.name + ")"

class Fics:
	"""A connection to the FICS server"""

	WHO_REGEX=re.compile('([0-9]+)([^0-9])(.+)')

	def __init__(self, user, password):
		self.connect(user, password)

	def connect(self, user, password):
		HOST = "freechess.org"

		self.tn = telnetlib.Telnet(HOST)

		greeting=self.tn.read_until(b"login: ")
		logging.debug(greeting.decode('ascii'))

		self.tn.write(user.encode('ascii') + b"\n")

		if password:
			self.tn.read_until(b"password: ")
			self.tn.write(password.encode('ascii') + b"\n")

		self.tn.read_until(b"fics%")  	
			
	def disconnect(self):
		self.tn.write(b"exit\n")

	def who(self):
		self.tn.write(b"who\n")
		playerStrings=self.tn\
			.read_until(b"players displayed")\
			.decode('ascii')\
			.split()

		self.tn.read_until(b"fics%")  	

		players = \
			frozenset(
				map(
					lambda tuple: Player(*tuple),
					map(
						lambda m : m.groups(),
						filter(
							None, 
							map(
								self.WHO_REGEX.fullmatch, 
								playerStrings)))))
		return players

class FicsAgent:
	DB_NAME='fics.db'

	def __init__(self, user, password):
		logging.info("Opening fics connection...")
		logging.debug("Username: %s Password: %s", user, password)
		self.fics = Fics(user, password)
		logging.info("done!")

		self.setupDB()
		
	def setupDB(self):
		con=sqlite3.connect(self.DB_NAME)
		with con:
			cur = con.cursor()
			cur.execute("""
				CREATE TABLE IF NOT EXISTS players(
					id 			INTEGER 	PRIMARY KEY AUTOINCREMENT, 
					name 		TEXT 		NOT NULL UNIQUE
				)
			""")
			cur.execute("""
				CREATE TABLE IF NOT EXISTS observations(
					id 			INTEGER 	PRIMARY KEY AUTOINCREMENT, 
					time 		TIMESTAMP 	DEFAULT CURRENT_TIMESTAMP, 
					playerid 	INT 		NOT NULL, 
					rating 		INT, 
					status 		TEXT 		DEFAULT 'OFFLINE',

					FOREIGN KEY(playerid) REFERENCES players(id)
				)
			""")
			con.commit()

	def close(self):
		self.cont = False
		self.fics.disconnect()

	def loop(self):
		try:
			while True:
				logging.debug("who!")
				playersFics=self.fics.who()

				con=sqlite3.connect(self.DB_NAME)
				with con:
					cur = con.cursor()
					playersDB = set(
						map(
							lambda x : x[0],
							cur.execute("SELECT name FROM players")))

					playersFicsSet = set(
						map(
							lambda p : p.name, 
							playersFics))
					
					newPlayers=playersFicsSet - playersDB
					logging.debug(
						"Players in DB: %s, players from fics: %s, players to be inserted: %s", 
						len(playersDB),
						len(playersFicsSet),
						len(newPlayers))

					logging.debug("playersFicsSet: %s", playersFicsSet)
					logging.debug("playersDB: %s", playersDB)
					
					# Insert new players:
					cur.executemany("INSERT INTO players (name) VALUES (?) ", map(lambda x : (x,), newPlayers))

					# Update status
					res= cur.executemany(
						"""
						INSERT INTO observations (playerid, rating, status) 
						SELECT 
							id, :rating, :status 
						FROM 
							players 
						WHERE 
							name = :name
						""",
						map(
							lambda p : {
								'status' : p.status, 
								'rating' : p.rating, 
								'name' : p.name
							},
							playersFics))

					logging.info("Inserted %s new players. Updated state on %s players. (rows updated :%s)", len(newPlayers), len(playersFics), con.total_changes)
					con.commit()
				time.sleep(10)

		except (KeyboardInterrupt, SystemExit):
			self.close()
			logging.info("Fics connection closed")
    

if __name__ == "__main__":
	logging.basicConfig(format='%(asctime)s %(levelname)-6s %(message)s', level=logging.INFO)
	agent = FicsAgent(sys.argv[1], sys.argv[2])

	agent.loop()
