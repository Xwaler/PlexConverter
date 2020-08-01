# PlexConverter

## Description
Multi-module tool to mux subtitles, convert and normalize media stored on a Plex server. You can use it on a 
single machine or use a VPS to handle the conversion part of the process. Your Plex libraries will 
automaticaly be surveyed and media needing conversion will be downloaded, processed, then re-uploaded in the 
same location.
#### If you use a VPS
You can locally use subtitler.py to add the subtitles and automaticaly upload them to your VPS for 
conversion. Every file sent for processing to the VPS will then be uploaded to your Plex server.

## Setup
#### Copy sample config file then edit necessary settings
```
cp config-sample.ini config.ini
nano config.ini
```
The converting machine needs an Plex access token and 
an authorization ssh key to your Plex server.
#### Install dependencies
```
pip install -r requirements.txt
```
#### Create a startup service file and store it in /etc/systemd/system/ (optional)
Here's an sample file
```
[Unit]
Description=PlexConverter service

[Service]
User=foobar 
WorkingDirectory=/home/foobar/PlexConverter/
ExecStart=/home/foobar/PlexConverter/start.sh 
ExecStop=/home/foobar/PlexConverter/stop.sh
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
```

## Usage
Start the background process (can be handled by a service as shown above)
```
./start.sh
```
Open the log window
```
./open.sh
```
#### If using a VPS and a local machine for subtitles, run on the latter
```
python src/subtitler.py
```
#### Add new media to Plex
- To add subtitles, convert and normalize, put them in the INPUT folder
- To only convert and normalize, put them in the CONVERTING folder
