# TODO: Push it inside deepgram_speech_to_text_streaming folder
import json
import asyncio
import base64
import logging
import threading
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from typing import AsyncGenerator, AsyncIterator, Any, Callable, Coroutine
from src.server.LLM import ChatOpenAI


class SpeechToText():
    def __init__(self) -> None:
        self.deepgram: DeepgramClient = DeepgramClient("091c1f6bcc4b4ded6787b36e9107b0a4280ffbf9")
        self.dg_connection = self.deepgram.listen.websocket.v("1")  # Creating websocket connection
        self.options = LiveOptions(model="nova-2")
        self.dg_connection.on(LiveTranscriptionEvents.Transcript, self.on_message)
        self.result_queue = asyncio.Queue()
        self.temp_sentence = ""
        self.openai = ChatOpenAI()

    async def on_message(self, result, **kwargs) -> None:
        sentence = result.channel.alternatives[0].transcript
        if len(sentence) == 0:
            return
        # print(f"speaker: {sentence}")
        # Need to pass it to llm models
        # yield sentence

        if not result.speech_final:
            self.temp_sentence = self.temp_sentence + sentence
        else:
            # This is the final part of the current sentence
            self.result_queue.put(self.temp_sentence+sentence) 
            self.temp_sentence=""
    
    # TODO: Also send websocket instance as a parameter to emit message from here
    async def transcription(self, input_stream: AsyncIterator[str], send_output_chunk: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        if self.dg_connection.start(self.options) is False:
            print("Failed to start connection")
            return
        print("transcribing ...")
        # async for data in input_stream:
        #     data = json.loads(data)
        #     # print(type(data))
        #     if data.get("type") == "input_audio_buffer.append" and "audio" in data:
        #         audio_base64 = data["audio"] # Need to format this chunks properly
        #         self.dg_connection.send(audio_base64)

        async def send_audio() -> None:
            try:
                async for data in input_stream:
                    data = json.loads(data)
                    # TODO: NEED TO FIX HERE NOT WORKING BECAUSE OF THIS [FORMAT]
                    if data.get("type") == "input_audio_buffer.append" and "audio" in data:
                        # audio_base64_decoded =  base64.b64decode(data["audio"]) # decoding base64
                        # print(f"base64 decode: {audio_base64_decoded} ", type(audio_base64_decoded))

                        # base64_string = audio_base64_decoded.decode("ascii")
                        # print(f"base64 ascii decode: {base64_string} ", type(base64_string))
                        
                        print("type-> ", data["audio"])
                        self.dg_connection.send(data["audio"])

                    # Send some terminate msg from input_stream so it will close this task
                    else:
                        print("Disconnected so terminating the process")
                        break
            except Exception as e:
                print("Terminated the send_audio process ",e)
            return

        try:
            # TODO: Putting it inside bec most probably when we disconnect input_stream will throw some err and in finally catch and cancel the send_audio process OR MAY BE SEND A TERMINATE MSG FROM INPUT_STREAM
            audio_task = asyncio.create_task(send_audio()) 

            while True:
                # Wait for a result from the queue
                transcript = await self.result_queue.get() # get method automatically removes the first element
                print(f"Processed transcript: {transcript}") # TODO: user role and content[RUN FIRE AND FORGET task to save it in db]
                
                # TODO: Process the transcript (e.g., pass to LLM models) [NEED TO ADD MEMORY SUPPORT]
                # AsyncGenerator return the streaming text from llm
                async for data in self.openai.streamResponse(msg=transcript):
                    if data["status"] == "success" and len(data["message"]) != 0:


                        # TODO: Send text from llm to text to Speech models 
                        # AsyncGenerator return the streaming audio form deepgram  await send_output_chunk(json.dumps(data))[websocket context -> return msg to client]
                        pass

                    elif data["status"] == "completed" and len(data["message"]) != 0:
                        pass
                        # TODO: Save assistant role and content in db
        finally:
            audio_task.cancel() 
            self.dg_connection.finish()



