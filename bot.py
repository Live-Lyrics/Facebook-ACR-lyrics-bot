import json
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from pymessenger.bot import Bot
from acrcloud.recognizer import ACRCloudRecognizer
import lyrics as minilyrics


app = Flask(__name__)

ACCESS_TOKEN = ""
VERIFY_TOKEN = ""
bot = Bot(ACCESS_TOKEN)

config = {
    'host': 'XXXXXXXX',
    'access_key': 'XXXXXXXX',
    'access_secret': 'XXXXXXXX',
    'timeout': 5  # seconds
}
error = 'Could not find lyrics.'


def reg(s):
    s = re.sub(r"[^\w\s]$", '', s)
    s = s.replace('$', 's')
    s = s.replace('&', 'and')
    s = s.replace("'", '_')
    s = re.sub(r"[-./\s\W]", '_', s)
    s = s.replace("__", '_')
    return s


def amalgama_lyrics(artist, song):
    artist, song = artist.lower(), song.lower()
    if 'the' in artist:
        artist = artist[4:]
    cn = artist[0]
    link = "http://www.amalgama-lab.com/songs/{}/{}/{}.html".format(cn, reg(artist), reg(song))
    r = requests.get(link)
    if r.status_code != 404:
        soup = BeautifulSoup(r.text, "html.parser")  # make soup that is parse-able by bs
        s = ''
        for strong_tag in soup.find_all("div", class_="translate"):
            if '\n' in strong_tag.text:
                s = s + strong_tag.text
            else:
                s = s + strong_tag.text + '\n'
        return s + link
    else:
        print("translate {} - {} not found".format(artist, song))


def get_genres(data):
    for music_list in data["metadata"]["music"]:
        for music_metadata in music_list:
            if music_metadata == "genres":
                genres = music_list[music_metadata][0]["name"]
                return genres


def get_youtube(artist, song):
    text = requests.get("https://www.youtube.com/results?search_query={} {}".format(artist, song)).text
    soup = BeautifulSoup(text, "html.parser")
    yid = soup.find('a', href=re.compile('/watch'))['href']
    li = soup.find('ul', {'class': 'yt-lockup-meta-info'}).contents[1].text
    views = int(''.join(filter(str.isdigit, li)))
    if views > 100000:
        return 'https://www.youtube.com{}'.format(yid)


def media(data, keys):
    for i in data['metadata']['music']:
        for key, value in i['external_metadata'].items():
            if keys == 'youtube' == key:
                yid = value['vid']
                return yid
            if keys == 'deezer' == key:
                did = value['track']['id']
                return did
            if keys == 'spotify' == key:
                sid = value['track']['id']
                return sid


def musixmatch(artist, song):
    try:
        searchurl = "https://www.musixmatch.com/search/{}-{}/tracks".format(artist, song)
        header = {"User-Agent": "curl/7.9.8 (i686-pc-linux-gnu) libcurl 7.9.8 (OpenSSL 0.9.6b) (ipv6 enabled)"}
        searchresults = requests.get(searchurl, headers=header)
        soup = BeautifulSoup(searchresults.text, 'html.parser')
        page = re.findall('"track_share_url":"(http[s?]://www\.musixmatch\.com/lyrics/.+?)","', soup.text)
        url = page[0]
        lyricspage = requests.get(url, headers=header)
        soup = BeautifulSoup(lyricspage.text, 'html.parser')
        lyrics = soup.text.split('"body":"')[1].split('","language"')[0]
        lyrics = lyrics.replace("\\n", "\n")
        lyrics = lyrics.replace("\\", "")
        print("{} - {} found in musixmatch".format(artist, song))
    except Exception:
        print("{} - {} not found in musixmatch".format(artist, song))
        return error
    return lyrics + url


def wikia(artist, song):
    lyrics = minilyrics.LyricWikia(artist, song)
    url = "http://lyrics.wikia.com/%s:%s" % (artist.replace(' ', '_'), song.replace(' ', '_'))
    if lyrics != 'error':
        return lyrics + url
    else:
        print("{} - {} not found in wikia".format(artist, song))
        lyrics = musixmatch(artist, song)
        return lyrics


@app.route("/", methods=['GET', 'POST'])
def hello():
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        else:
            return 'Invalid verification token'

    if request.method == 'POST':
        output = request.get_json()
        for event in output['entry']:
            messaging = event['messaging']
            for x in messaging:
                if x.get('message'):
                    recipient_id = x['sender']['id']
                    if x['message'].get('text'):
                        bot.send_text_message(recipient_id, 'please send audio')

                    if x['message'].get('attachments'):
                        for att in x['message'].get('attachments'):
                            if att['type'] == 'audio':
                                payload = att['payload']['url']
                                file = requests.get(payload)
                                if file.status_code == 200:
                                    filename = payload.split('/')[5].split('.')[0]
                                    with open(filename, 'wb') as f:
                                        for chunk in file:
                                            f.write(chunk)

                                    recogn = ACRCloudRecognizer(config)
                                    metadata = recogn.recognize_by_file(filename, 0)
                                    data = json.loads(metadata)

                                    if data['status']['code'] == 0:
                                        with open('{}.json'.format(filename), 'w', encoding='utf8') as outfile:
                                            json.dump(data, outfile, indent=4, sort_keys=True)

                                        artist = data['metadata']['music'][0]['artists'][0]['name']
                                        song = data['metadata']['music'][0]['title']
                                        if song.count(" - ") == 1:
                                            song, garbage = song.rsplit(" - ", 1)
                                        song = re.sub("[(\[].*?[)\]]", "", song).strip()
                                        about = "{} - {}".format(artist, song)
                                        bot.send_text_message(recipient_id, about)

                                        genres = get_genres(data)
                                        if genres != 'Classical':
                                            lyrics_text = wikia(artist, song).split('\n\n')
                                            for couplet in lyrics_text:
                                                bot.send_text_message(recipient_id, couplet)
                                            lyrics_translate = amalgama_lyrics(artist, song).split('\n\n')
                                            if lyrics_translate is not None:
                                                for couplet in lyrics_translate:
                                                    bot.send_text_message(recipient_id, couplet)
                                            else:
                                                bot.send_text_message(recipient_id, 'Translate not found')

                                            yid = media(data, 'youtube')
                                            if yid is not None:
                                                y_link = 'https://www.youtube.com/watch?v=' + yid
                                                bot.send_text_message(recipient_id, y_link)
                                            else:
                                                y_link = get_youtube(artist, song)
                                                if y_link is not None:
                                                    bot.send_text_message(recipient_id, y_link)
                                        else:
                                            bot.send_text_message(recipient_id, 'this is classical melody')

                                        sid = media(data, 'spotify')
                                        if sid is not None:
                                            s_link = 'https://open.spotify.com/track/{}'.format(sid)
                                            bot.send_text_message(recipient_id, s_link)
                                        else:
                                            print("{} - {} not found in spotify".format(artist, song))

                                        did = media(data, 'deezer')
                                        if did is not None:
                                            d_link = 'http://www.deezer.com/track/{}'.format(str(did))
                                            r = requests.get(d_link)
                                            if r.status_code != 404:
                                                bot.send_text_message(recipient_id, d_link)
                                        else:
                                            print("{} - {} not found in deezer".format(artist, song))
                                    else:
                                        bot.send_text_message(recipient_id, 'songs not found')
                                else:
                                    print('audio not find')
                else:
                    pass
        return "Success"


if __name__ == "__main__":
    app.run(port=5002, debug=True)
