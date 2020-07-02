import os
import pytube
from google.cloud import storage
import json
import io
from google.cloud import speech_v1
from google.cloud.speech_v1 import enums
from google.cloud.speech_v1 import types

import subprocess
from pydub.utils import mediainfo
import math
import datetime
import srt 
import moviepy.editor as mp 

os.environ["GOOGLE_APPLICATION_CREDENTIALS"]="alien-fold-281005-ad5ab61eb021.json"

BUCKET_NAME = "subtitle-generation" # update this with your bucket name

from apiclient.discovery import build

DEVELOPER_KEY = 'AIzaSyCyRpAu_8Vm_mYSMEjDoqs4yD_YCrcTDSs'
youtube = build('youtube', 'v3', developerKey=DEVELOPER_KEY)


def get_youtube_title(id):
    results = youtube.videos().list(id=id, part='snippet').execute()
    for result in results.get('items', []):
        return (result['snippet']['title']) 
    


def generate_subtitle(link):
    video_id = link.split('=')[-1]
    original_name = get_youtube_title(video_id)
    video_path = download_video(link)
    if video_path == None:
        return None
    channels, bit_rate, sample_rate = video_info(video_path)
    blob_name = video_to_audio(video_path, "audio.mp3", channels, bit_rate, sample_rate)
    gcs_uri = f"gs://{BUCKET_NAME}/{blob_name}"
    response = long_running_recognize(gcs_uri, channels, sample_rate)

    transcriptions = get_transcriptions(response)

    with open('data/meta.json', 'r+') as meta_file : 
        data = json.load(meta_file)
        new_filename = write_srt_file(transcriptions, len(data) + 1)
        data.append({
            'index' : len(data) + 1,
            'original_url' : link,
            'original_name' : original_name,
            'subtitle_file' : new_filename
        })
        meta_file.seek(0)
        meta_file.write(json.dumps(data))
        meta_file.truncate()
        meta_file.close()

    
    return get_json_response(transcriptions, len(data))

def edit_file(filename, edit_data, id):
    
    with open(f'data/subtitles/{filename}', 'w') as f : 
        transcriptions = []
        return_data = []
        for sub in edit_data:
            new_sub = srt.Subtitle(
                sub['index'], 
                srt.srt_timestamp_to_timedelta(sub['start']),
                srt.srt_timestamp_to_timedelta(sub['end']),
                sub['content']
            )
            transcriptions.append(new_sub)
            return_data.append({
                'index' : sub['index'],
                'start' : sub['start'],
                'end' : sub['end'],    
                'content' : sub['content']
            })

        new_subtitles = srt.compose(transcriptions)
        f.write(new_subtitles)
        f.close()

        return get_json_response(return_data, id)



def get_subtitles_from_file(filename, index, url=None, name=None) : 
    transcriptions = []
    with open(f'data/subtitles/{filename}') as f : 
        text = f.read()
        subtitles = srt.parse(text)
        f.close()

    for i, sub in enumerate(subtitles) : 
        transcriptions.append({
            'index' : i+1,
            'start' : srt.timedelta_to_srt_timestamp(sub.start),
            'end' : srt.timedelta_to_srt_timestamp(sub.end),
            'content' : sub.content 
        })

    return get_json_response(transcriptions, index, url, name)

def upload_blob(bucket_name, source_file_name, destination_blob_name):
    """Uploads a file to the bucket."""
    # bucket_name = "your-bucket-name"
    # source_file_name = "local/path/to/file"
    # destination_blob_name = "storage-object-name"

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(source_file_name)

    print(
        "File {} uploaded to {}.".format(
            source_file_name, destination_blob_name
        )
    )

def download_video(link):
    print('Downloading Video....')
    try: 
        yt = pytube.YouTube(link) 
        video_path = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').asc().first().download()

    except Exception as e :
        print(e) 
        print("Connection Error") 
        return None#to handle exception 
    
    print(video_path)

    new_path = video_path.split('/')
    new_filename = f"video.mp4"
    new_path[-1]= new_filename
    new_path='/'.join(new_path)
    os.rename(video_path, new_path)
    print(new_path)
    return new_path

def video_info(video_filepath):
    """ this function returns number of channels, bit rate, and sample rate of the video"""

    video_data = mediainfo(video_filepath)
    channels = video_data["channels"]
    bit_rate = video_data["bit_rate"]
    sample_rate = video_data["sample_rate"]

    return channels, bit_rate, sample_rate

def video_to_audio(video_filepath, audio_filename, video_channels, video_bit_rate, video_sample_rate):
    # Insert Local Video File Path  
    clip = mp.VideoFileClip(video_filepath) 

    # Insert Local Audio File Path 
    clip.audio.write_audiofile(audio_filename) 
    #command = f"ffmpeg -i {video_filepath} -b:a {video_bit_rate} -ac {video_channels} -ar {video_sample_rate} -vn {audio_filename}"
    
    subprocess.call(audio_filename, shell=True)
    blob_name = f"audios/{audio_filename}"
    upload_blob(BUCKET_NAME, audio_filename, blob_name)
    return blob_name

def long_running_recognize(storage_uri, channels, sample_rate):
    client = speech_v1.SpeechClient()

    config = {
        "language_code": "en-US",
        "sample_rate_hertz": int(sample_rate),
        "encoding": enums.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED,
        "audio_channel_count": int(channels),
        "enable_word_time_offsets": True,
        "model": "video",
        "enable_automatic_punctuation":True
    }
    audio = {"uri": storage_uri}

    operation = client.long_running_recognize(config, audio)

    print(u"Waiting for operation to complete...")
    response = operation.result()
    return response

def get_transcriptions(response, bin_size=3):
    transcriptions = []
    index = 0
 
    for result in response.results:
        try:
            if result.alternatives[0].words[0].start_time.seconds:
                # bin start -> for first word of result
                start_sec = result.alternatives[0].words[0].start_time.seconds 
                start_microsec = result.alternatives[0].words[0].start_time.nanos * 0.001
            else:
                # bin start -> For First word of response
                start_sec = 0
                start_microsec = 0 
            end_sec = start_sec + bin_size # bin end sec
            
            # for last word of result
            last_word_end_sec = result.alternatives[0].words[-1].end_time.seconds
            last_word_end_microsec = result.alternatives[0].words[-1].end_time.nanos * 0.001
            
            # bin transcript
            transcript = result.alternatives[0].words[0].word
            
            index += 1 # subtitle index

            for i in range(len(result.alternatives[0].words) - 1):
                try:
                    word = result.alternatives[0].words[i + 1].word
                    word_start_sec = result.alternatives[0].words[i + 1].start_time.seconds
                    word_start_microsec = result.alternatives[0].words[i + 1].start_time.nanos * 0.001 # 0.001 to convert nana -> micro
                    word_end_sec = result.alternatives[0].words[i + 1].end_time.seconds
                    word_end_microsec = result.alternatives[0].words[i + 1].end_time.nanos * 0.001

                    if word_end_sec < end_sec:
                        transcript = transcript + " " + word
                    else:
                        previous_word_end_sec = result.alternatives[0].words[i].end_time.seconds
                        previous_word_end_microsec = result.alternatives[0].words[i].end_time.nanos * 0.001
                        
                        # append bin transcript
                        # transcriptions.append(srt.Subtitle(index, datetime.timedelta(0, start_sec, start_microsec), datetime.timedelta(0, previous_word_end_sec, previous_word_end_microsec), transcript))
                        transcriptions.append({
                            'index' : index,
                            'start' : srt.timedelta_to_srt_timestamp(datetime.timedelta(0, start_sec, start_microsec)),
                            'end' : srt.timedelta_to_srt_timestamp(datetime.timedelta(0, previous_word_end_sec, previous_word_end_microsec)),
                            'content' : transcript 
                        })
                        # reset bin parameters
                        start_sec = word_start_sec
                        start_microsec = word_start_microsec
                        end_sec = start_sec + bin_size
                        transcript = result.alternatives[0].words[i + 1].word
                        
                        index += 1
                except IndexError:
                    pass
            # append transcript of last transcript in bin
            # transcriptions.append(srt.Subtitle(index, datetime.timedelta(0, start_sec, start_microsec), datetime.timedelta(0, last_word_end_sec, last_word_end_microsec), transcript))
            transcriptions.append({
                'index' : index,
                'start' : srt.timedelta_to_srt_timestamp(datetime.timedelta(0, start_sec, start_microsec)),
                'end' : srt.timedelta_to_srt_timestamp(datetime.timedelta(0, last_word_end_sec, last_word_end_microsec)),
                'content' : transcript 
            })
            index += 1
        except IndexError:
            pass
        
    return transcriptions

def write_srt_file(transcriptions, id):
    v_transcriptions = []
    for trans in transcriptions:
        index = trans['index']
        start = srt.srt_timestamp_to_timedelta(trans['start'])
        end = srt.srt_timestamp_to_timedelta(trans['end'])
        content = trans['content']
        v_transcriptions.append(srt.Subtitle(index, start, end, content))

    
    new_filename = f'subtitles_{id}.srt'
    subtitles = srt.compose(v_transcriptions)
    with open(f'data/subtitles/{new_filename}', "w") as f:
        f.write(subtitles)
        f.close()
    
    return new_filename

def get_json_response(transcriptions, index, url=None, name=None):
    return json.dumps({
        'transcriptions' : transcriptions,
        'id' : index,
        'original_url' : url,
        'original_name' : name
    })