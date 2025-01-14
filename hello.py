# Example filename: main.py

import httpx
import logging
# from deepgram.utils import verboselogs
import threading

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

# URL for the realtime streaming audio you would like to transcribe
URL = "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"

class TranscriptCollector:
    def __init__(self):
        self.reset()

    def reset(self):
        self.transcript_parts = []

    def add_part(self, part):
        self.transcript_parts.append(part)

    def get_full_transcript(self):
        return ' '.join(self.transcript_parts)

transcript_collector = TranscriptCollector()


def main():
    try:
        # use default config
        deepgram: DeepgramClient = DeepgramClient("091c1f6bcc4b4ded6787b36e9107b0a4280ffbf9")

        # Create a websocket connection to Deepgram
        dg_connection = deepgram.listen.websocket.v("1")

        def on_message(self, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            print (result)
            
            if not result.speech_final:
                transcript_collector.add_part(sentence)
            else:
                # This is the final part of the current sentence
                transcript_collector.add_part(sentence)
                full_sentence = transcript_collector.get_full_transcript()
                print(f"speaker: {full_sentence}")
                # Reset the collector for the next sentence
                transcript_collector.reset()

        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

        # connect to websocket
        options = LiveOptions(model="nova-2")

        print("\n\nPress Enter to stop recording...\n\n")
        if dg_connection.start(options) is False:
            print("Failed to start connection")
            return

        lock_exit = threading.Lock()
        exit = False

        # define a worker thread
        def myThread():
            with httpx.stream("GET", URL) as r:
                for data in r.iter_bytes():
                    print("audio chunk -> ", type(data))
                    lock_exit.acquire()
                    if exit:
                        break
                    lock_exit.release()

                    dg_connection.send(data)

        # start the worker thread
        myHttp = threading.Thread(target=myThread)
        myHttp.start()

        # signal finished
        input("")
        lock_exit.acquire()
        exit = True
        lock_exit.release()

        # Wait for the HTTP thread to close and join
        myHttp.join()

        # Indicate that we've finished
        dg_connection.finish()

        print("Finished")

    except Exception as e:
        print(f"Could not open socket: {e}")
        return

if __name__ == "__main__":
    main()