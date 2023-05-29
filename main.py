import os
import re
import nltk
import librosa
import logging
import pycountry
import datefinder
import numpy as np
import mysql.connector
import speech_recognition
from flask_cors import CORS
from geotext import GeoText
from librosa import feature
from datetime import datetime
import speech_recognition as sr
from scipy.spatial import distance
from nltk import pos_tag, ne_chunk
from nltk.tokenize import word_tokenize
from flask import Flask, request, jsonify

# Establish a connection to the MySQL database
connection = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='thefarre'
)

cursor = connection.cursor()

app = Flask(__name__)
CORS(app)

# Download the required resources
nltk.download('maxent_ne_chunker')
nltk.download('words')
nltk.download('punkt')

recognizer = sr.Recognizer()

app.logger.setLevel(logging.DEBUG)


@app.route('/audio', methods=['POST'])
def processAudio():
    text = ""
    user_id = 0
    if request.method == 'POST':
        email = request.form.get('email')  # Extract the text from the form data
        # Check if the email already exists in the `user` table
        check_email_query = "SELECT `id` FROM `users` WHERE `email` = %s"
        check_email_values = (email,)
        cursor.execute(check_email_query, check_email_values)
        existing_user = cursor.fetchone()

        if existing_user:
            # If the email exists, retrieve the existing user's ID
            user_id = existing_user[0]
        else:
            # If the email doesn't exist, insert the new user and retrieve the generated ID
            user_query = "INSERT INTO `users` (`email`) VALUES (%s)"
            user_values = (email,)
            cursor.execute(user_query, user_values)
            user_id = cursor.lastrowid

        audio_file = request.files['audio']
        audio_path = 'audio.wav'
        audio_file.save(audio_path)
        response2 = {}

        # Call voice identification function
        identified_file = compare_audio_files(audio_path)
        if identified_file:
            # Return from MySQL database the user where audio_file is equal to identified_file
            get_user_query = "SELECT * FROM `people` WHERE `audio_file` = %s AND `user_id` = %s"
            get_user_values = (identified_file, user_id)
            cursor.execute(get_user_query, get_user_values)
            existing_user = cursor.fetchone()

            print(existing_user)
            if existing_user:
                # Extract user information from the database
                existing_user_id = existing_user[1]
                existing_first_name = existing_user[2]
                existing_last_name = existing_user[3]
                existing_birthday = existing_user[5]
                existing_city = existing_user[4]
                existing_country = existing_user[6]
                existing_phone_number = existing_user[7]

                # Prepare response for existing profile
                response2 = {
                    'firstName': existing_first_name,
                    'lastName': existing_last_name,
                    'birthday': existing_birthday,
                    'city': existing_city,
                    'country': existing_country,
                    'phoneNumber': existing_phone_number,
                    'user_id': existing_user_id,
                    'audio_file': identified_file,
                }
                print(f"Identified file: {identified_file}")
                print("Existing profile:", response2)
            else:
                response2 = {
                    'firstName': None,
                    'lastName': None,
                    'birthday': None,
                    'city': None,
                    'country': None,
                    'phoneNumber': None,
                    'user_id': None,
                    'audio_file': None,
                }
                print("No matching file found.")
        else:
            print("No matching file found.")

        # Perform speech recognition on the audio file
        with sr.AudioFile(audio_path) as audio:
            audio_data = recognizer.record(audio)
            try:
                text = recognizer.recognize_google(audio_data)
                # Handle the recognized text
                print(text)
            except speech_recognition.UnknownValueError:
                print("Speech recognition could not understand audio")
            except speech_recognition.RequestError as e:
                print(f"Could not request results from Google Speech Recognition service; {e}")

        # Initialize variables
        first_name = None
        last_name = None
        date_of_birth = None
        city = None
        country = None
        phone_number = None

        # Tokenize the text into words
        words = word_tokenize(text)

        # Perform part-of-speech tagging and named entity recognition
        tagged_words = pos_tag(words)
        named_entities = ne_chunk(tagged_words)

        # Iterate over named entities to extract information
        for entity in named_entities:
            if hasattr(entity, 'label') and entity.label() == 'PERSON':
                for name in entity.leaves():
                    if first_name is None:
                        first_name = name[0]
                    else:
                        last_name = name[0]
                        break

        # Save audio file with first and last name
        if first_name and last_name:
            current_datetime = datetime.now().strftime("%Y%m%d%H%M%S")
            new_file_name = f"{user_id}_{current_datetime}_{first_name}_{last_name}.wav"
            new_audio_path = os.path.join('audio', new_file_name)
            os.rename(audio_path, new_audio_path)
        else:
            new_file_name = generate_default_name(user_id)
            new_audio_path = os.path.join('unknown', new_file_name)
            os.rename(audio_path, new_audio_path)

        # Extract phone number using regular expressions
        phone_number_pattern = r'\+?\d{9,}'
        phone_numbers = re.findall(phone_number_pattern, text)
        phone_number = phone_numbers[0] if phone_numbers else None

        # Use datefinder to extract the date of birth from the text
        matches = datefinder.find_dates(text)
        for match in matches:
            if match.year > 1900:
                date_of_birth = match.strftime("%d %B %Y")
                break

        # Extract city and country using GeoText
        places = GeoText(text)
        cities = places.cities
        countries = []

        for country_code in places.country_mentions.keys():
            try:
                country_name = pycountry.countries.get(alpha_2=country_code).name
                countries.append(country_name)
            except KeyError:
                pass

        if len(cities) > 0:
            city = cities[0]
        if len(countries) > 0:
            country = countries[0]
            if country not in text:
                country = None

        if city is None and country is None:
            # Split the text by spaces and check again
            parts = [part.strip() for part in text.split()]
            for part in parts:
                places = GeoText(part)
                if len(places.cities) > 0 and city is None:
                    city = places.cities[0]
                if len(places.country_mentions) > 0 and country is None:
                    for country_code in places.country_mentions.keys():
                        try:
                            country_name = pycountry.countries.get(alpha_2=country_code).name
                            if country_name in text:
                                country = country_name
                                break
                        except KeyError:
                            pass

        # Prepare the response
        response1 = {
            'firstName': first_name,
            'lastName': last_name,
            'birthday': date_of_birth,
            'city': city,
            'country': country,
            'phoneNumber': phone_number,
            'user_id': user_id,
            'audio_file': new_file_name,
        }

        combined_response = {
            'newProfile': response1,
            'existingProfile': response2
        }

        # Commit the changes to the database
        connection.commit()

        return jsonify(combined_response)

    return jsonify('Hello World')


@app.route('/text', methods=['POST'])
def processText():
    text = ""
    user_id = 0
    if request.method == 'POST':
        email = request.form.get('email')  # Extract the text from the form data
        print(email)
        # Check if the email already exists in the `user` table
        check_email_query = "SELECT `id` FROM `users` WHERE `email` = %s"
        check_email_values = (email,)
        cursor.execute(check_email_query, check_email_values)
        existing_user = cursor.fetchone()

        if existing_user:
            # If the email exists, retrieve the existing user's ID
            user_id = existing_user[0]
        else:
            # If the email doesn't exist, insert the new user and retrieve the generated ID
            user_query = "INSERT INTO `users` (`email`) VALUES (%s)"
            user_values = (email,)
            cursor.execute(user_query, user_values)
            user_id = cursor.lastrowid

        text = request.form.get('text')
        # Initialize variables
        first_name = None
        last_name = None
        date_of_birth = None
        city = None
        country = None
        phone_number = None

        # Tokenize the text into words
        words = word_tokenize(text)

        # Perform part-of-speech tagging and named entity recognition
        tagged_words = pos_tag(words)
        named_entities = ne_chunk(tagged_words)

        # Iterate over named entities to extract information
        for entity in named_entities:
            if hasattr(entity, 'label') and entity.label() == 'PERSON':
                for name in entity.leaves():
                    if first_name is None:
                        first_name = name[0]
                    else:
                        last_name = name[0]
                        break

        # Extract phone number using regular expressions
        phone_number_pattern = r'\+?\d{9,}'
        phone_numbers = re.findall(phone_number_pattern, text)
        phone_number = phone_numbers[0] if phone_numbers else None

        # Use datefinder to extract the date of birth from the text
        matches = datefinder.find_dates(text)
        for match in matches:
            if match.year > 1900:
                date_of_birth = match.strftime("%d %B %Y")
                break

        # Extract city and country using GeoText
        places = GeoText(text)
        cities = places.cities
        countries = []

        for country_code in places.country_mentions.keys():
            try:
                country_name = pycountry.countries.get(alpha_2=country_code).name
                countries.append(country_name)
            except KeyError:
                pass

        if len(cities) > 0:
            city = cities[0]
        if len(countries) > 0:
            country = countries[0]
            if country not in text:
                country = None

        if city is None and country is None:
            # Split the text by spaces and check again
            parts = [part.strip() for part in text.split()]
            for part in parts:
                places = GeoText(part)
                if len(places.cities) > 0 and city is None:
                    city = places.cities[0]
                if len(places.country_mentions) > 0 and country is None:
                    for country_code in places.country_mentions.keys():
                        try:
                            country_name = pycountry.countries.get(alpha_2=country_code).name
                            if country_name in text:
                                country = country_name
                                break
                        except KeyError:
                            pass

        # Prepare the response
        response1 = {
            'firstName': first_name,
            'lastName': last_name,
            'birthday': date_of_birth,
            'city': city,
            'country': country,
            'phoneNumber': phone_number,
            'user_id': user_id,
            'audio_file': None,
        }

        combined_response = {
            'newProfile': response1,
            'existingProfile': None
        }

        # Commit the changes to the database
        connection.commit()

        return jsonify(combined_response)

    return jsonify('Hello World')


def generate_default_name(user):
    count = 1
    while True:
        file_name = f"user_{user}_{count}.wav"
        if not os.path.exists(os.path.join('unknown', file_name)):
            return file_name
        count += 1


def compare_audio_files(audio_path):
    # Load audio files
    audio1, sample_rate1 = librosa.load(audio_path)

    # Extract audio features (MFCC)
    mfcc1 = librosa.feature.mfcc(y=audio1, sr=sample_rate1)

    # Define a threshold for similarity score
    similarity_threshold = 65
    max_similarity_score = 0
    max_similarity_file = None

    # Iterate through all audio files in the "audio" folder
    audio_folder = "audio"
    for filename in os.listdir(audio_folder):
        if filename.endswith(".wav"):
            audio_file = os.path.join(audio_folder, filename)
            audio2, sample_rate2 = librosa.load(audio_file)
            mfcc2 = librosa.feature.mfcc(y=audio2, sr=sample_rate2)
            similarity_score = distance.euclidean(np.mean(mfcc1, axis=1), np.mean(mfcc2, axis=1))

            if similarity_score > max_similarity_score:
                max_similarity_score = similarity_score
                max_similarity_file = filename

    if max_similarity_score >= similarity_threshold:
        print(f"Max Similarity Score: {max_similarity_score} + {max_similarity_file}")
        return max_similarity_file
    else:
        print(f"No matching file above similarity threshold.")
        return None


@app.route('/save', methods=['GET', 'POST'])
def save():
    # Retrieve data from the POST request
    data = request.json
    first_name = data.get('firstName')
    last_name = data.get('lastName')
    date_of_birth = data.get('birthday')
    city = data.get('city')
    country = data.get('country')
    phone_number = data.get('phoneNumber')
    user_id = data.get('user_id')
    audio_file = data.get('audio_file')

    # Save user profile to the "people" table
    insert_query = """
        INSERT INTO `people` (first_name, last_name, city, country, date_of_birth, phone_number, audio_file, user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    insert_values = (
        first_name,
        last_name,
        city,
        country,
        date_of_birth,
        phone_number,
        audio_file,
        user_id
    )
    cursor.execute(insert_query, insert_values)
    connection.commit()

    # Prepare the response
    response = {
        'firstName': first_name,
        'lastName': last_name,
        'birthday': date_of_birth,
        'city': city,
        'country': country,
        'phoneNumber': phone_number,
        'user_id': user_id,
        'audio_file': audio_file
    }

    return jsonify(response)


if __name__ == '__main__':
    app.run()

# Close the database connection
connection.close()
