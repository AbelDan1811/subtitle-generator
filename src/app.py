from flask import Flask, request, send_from_directory
import generator
from flask_cors import CORS, cross_origin
import json

app = Flask(import_name=__name__, static_url_path='')
app.config['SERVE_FILE_FOLDER'] = '/home/dungdang/xltn/subtitle-generator/data/subtitles'
CORS(app)


@app.route('/subtitles/<id>/file', methods=['GET'])
def download_file(id):
    print(id)
    with open('data/meta.json') as meta_file:
        data = json.load(meta_file)
        existed_data = [entry for entry in data if entry['index'] == int(id)]
        meta_file.close()
        if len(existed_data) == 0: 
            return None
        print(existed_data[0]['subtitle_file'])
        return send_from_directory(app.config['SERVE_FILE_FOLDER'], existed_data[0]['subtitle_file'], as_attachment=True, )

@app.route('/subtitles', methods=['GET'])
def get_all_subtitles():
    with open('data/meta.json') as meta_file:
        data = json.load(meta_file)
        meta_file.close()
        return json.dumps(data)



@app.route('/generate', methods=['POST'])
def generate(): 
    video_url = request.get_json().get('video_url')
    with open('data/meta.json') as meta_file:
        data = json.load(meta_file)
        existed_data = [entry for entry in data if entry['original_url'] == video_url]
        meta_file.close()

        if len(existed_data) != 0: 
            return generator.get_subtitles_from_file(existed_data[0]['subtitle_file'], existed_data[0]['index'])
    return generator.generate_subtitle(video_url)

@app.route('/subtitles/<id>/edit', methods=['POST'])
def edit_file(id):
    edit_data = request.get_json()
    with open('data/meta.json') as meta_file:
        data = json.load(meta_file)
        existed_data = [entry for entry in data if entry['index'] == int(id)]
        meta_file.close()
        if len(existed_data) == 0: 
            return None

        return generator.edit_file(existed_data[0]['subtitle_file'], edit_data ,existed_data[0]['index'])

@app.route('/subtitles/<id>', methods=['GET'])
def get_file(id):
    with open('data/meta.json') as meta_file:
        data = json.load(meta_file)
        existed_data = [entry for entry in data if entry['index'] == int(id)]
        meta_file.close()
        print(existed_data)
        if len(existed_data) == 0: 
            return None

        return generator.get_subtitles_from_file(existed_data[0]['subtitle_file'], existed_data[0]['index'], existed_data[0]['original_url'], existed_data[0]['original_name'])
        
app.run(debug=True)