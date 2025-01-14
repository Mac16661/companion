import uvicorn
import asyncio
import json
import datetime
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route, WebSocketRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocket
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.background import BackgroundTask
from bson import json_util
from bson import ObjectId


from src.server.utils import  websocketStream, speech2text, websocket_stream
from src.server.STT import SpeechToText
from src.server.LLM import ChatOpenAI
from src.server.KB import KnowledgeBase
from src.server.prompt import INSTRUCTIONS
from src.server.tools import TOOLS
from src.server.langchain_openai_voice import OpenAIVoiceReactAgent


# Serving web page
async def premiumHomepage(request):
    with open("src/server/static/premium/index.html") as f:
        html = f.read()
        return HTMLResponse(html)
    
async def freebieHomepage(request):
    with open("src/server/static/freebie/index.html") as f:
        html = f.read()
        return HTMLResponse(html)
    
# Need to make some performance upgrade using asyncio/multithreading for db ops 
async def handleChat(request: Request):
    # request contains: user_content, system_content, group_id, user_id and optional param: image, audio

    try: 
        userMsg = await request.json()

        # print(userMsg, type(userMsg))
    
        # TODO: do some validation check

        # TODO: Try to fire the db ops at the same time using asyncio 
        # Knowledge base
        kb = KnowledgeBase()

        # personal message from graph db (use non-blocking)
        personalData = kb.fetchPersonalData(userMsg["user_id"])
        # long-term and short-term memory (use non-blocking)
        shortTermMemory = kb.fetchShortTermChat(userMsg) or []
        # TODO: Should pass it as a tool to llm
        # longTermMemory = await kb.fetchChatHistory(userMsg) or []

        # context from the knowledge base
        # relevantContext, web_img = kb.fetchContext(userMsg["user_content"])
        #TODO: Search web instead of local

        sysMsg = {
            "role": "system",
            "content": userMsg['system_content'] + ".Here are some user personal information, strictly use provided data points to chat like a real human and give more personalized example and analogies: \n" + str(personalData)
        }

        # print("SYS MSG: ", sysMsg)

        currMsg = {
            "role":"user",
            "content":userMsg['user_content'] 
        }

        MsgSave = {
                "group_id": userMsg["group_id"],
                "user_id": userMsg["user_id"],
                "role": currMsg["role"],
                "content": currMsg["content"], 
                "image": "",
                "audio": "",
                "summery": "",
                "createdAt": datetime.datetime.now()
        }

        currMsg["content"] = "\nQuery: " + userMsg['user_content']
        # currMsg["content"] = "\nQuery: " + userMsg['user_content']

        # TODO: Dont use image inputs with tool calling agents
        if "image" in userMsg and userMsg["image"] != "":
            content = [{"type": "text", "text": currMsg["content"]},
                    {"type":"image_url", "image_url": {"url":userMsg["image"]}}]
            
            currMsg["content"] = content
            MsgSave["image"] = userMsg["image"] # for database
            print("image processing required ...")

        elif "audio" in userMsg and userMsg["audio"] != "":
            transcription = await speech2text(userMsg["audio"])
            print(transcription, type(transcription))
            
            if transcription == "":
                return JSONResponse({"err": "Failed to process audio"}) 

            currMsg["content"] = str(transcription) + currMsg["content"]

            MsgSave["audio"] = userMsg["audio"] # for database
            print("audio processing required ...")
        
        # print("USER QUERY:: ",currMsg)

        # TODO: asyncio Fire and forget task here
        # asyncio.create_task(saveUserChatInferredPersonalData())
        kb.saveUserChatInferredPersonalData(MsgSave)

        # may need to add long-term msg for now
        msg = [sysMsg] + shortTermMemory + [currMsg]

        # print("\nUSER:",msg)

        # Use this for image only
        llm = ChatOpenAI()
        # gptResponse = await llm.simpleResponse(msg=msg)

        # TODO: Tool calling agent
        gptResponse, web_img = llm.simpleResponseWithToolCall(msg=msg, kb=kb)
        # print("Answer -> ", gptResponse)

        assistant = {
            "role": 'assistant',
            "content": gptResponse.content,
            "group_id": userMsg["group_id"],
            "user_id": userMsg["user_id"],
        }

        # Insert image reference
        if len(web_img) > 0:
            assistant["image"] = web_img[0]
            web_img_result = "\n".join(web_img)
            append_res = assistant["content"] + "\n\n\n" + "Image references:\n" + web_img_result + "\n"
            assistant["content"] = append_res

        # print("web img res in app-> ",web_img)

        # TODO: asyncio for save to db [formate gpt response for db] not working like fire and forget
        kb.saveAssistantChatSummarizeData(assistant)
        
        return JSONResponse({"data": [assistant]})
    except Exception as e:
        print("ERROR occurred while processing chat ", e)
        return JSONResponse({"err": "Internal server error"})

# SpeechToSpeech freebie realtime version[for freebie]
async def handleCallFreebie(websocket: WebSocket):
    await websocket.accept()

    # try:
        
    #     async for data in websocketStream(websocket):
    #         data = json.loads(data)
    #         # print(type(data))
    #         if data.get("type") == "input_audio_buffer.append" and "audio" in data:
    #             audio_base64 = data["audio"]
    #             # print(data["audio"].encode('utf-8'))
    #             await saveAudioLocally(audio_base64, "rce_audio.raw")
    #         else:
    #             print("New type data:", data)
    # except Exception as e:
    #     print("Internal server error while saving audio: ", e)

    browserReceiveStream = websocketStream(websocket)

    TTS = SpeechToText()
    await TTS.transcription(browserReceiveStream, websocket.send_text)

async def handelCallPremium(websocket: WebSocket):
    await websocket.accept()

    browser_receive_stream = websocket_stream(websocket)

    agent = OpenAIVoiceReactAgent(
        model="gpt-4o-realtime-preview",
        tools=TOOLS,
        instructions=INSTRUCTIONS,
    )

    await agent.aconnect(browser_receive_stream, websocket.send_text)

# TODO: add one new function to handle initial user profile function
async def handleInitialChat(request: Request):
    # request contains: user_content, system_content, group_id, user_id and optional param: image, audio

    try: 
        userMsg = await request.json()

        # print(userMsg, type(userMsg))
    
        # TODO: do some validation check

        # TODO: Try to fire the db ops at the same time using asyncio 
        # Knowledge base
        kb = KnowledgeBase()

        # personal message from graph db (use non-blocking)
        personalData = kb.fetchPersonalData(userMsg["user_id"])
        # long-term and short-term memory (use non-blocking)
        shortTermMemory = kb.fetchShortTermChat(userMsg) or []
        # TODO: Should pass it as a tool to llm
        # longTermMemory = await kb.fetchChatHistory(userMsg) or []

        # context from the knowledge base
        # relevantContext = kb.fetchContext(userMsg["user_content"])

        sysMsg = {
            "role": "system",
            "content": userMsg['system_content'] +  str(personalData)
        }

        # print("SYS MSG: ", sysMsg)

        currMsg = {
            "role":"user",
            "content":userMsg['user_content'] 
        }

        MsgSave = {
                "group_id": userMsg["group_id"],
                "user_id": userMsg["user_id"],
                "role": currMsg["role"],
                "content": currMsg["content"], 
                "image": "",
                "audio": "",
                "summery": "",
                "createdAt": datetime.datetime.now()
        }

        # currMsg["content"] = "Context: "+ relevantContext + "\nQuery: " + userMsg['user_content']

        # TODO: CURRENT PRICE TEAR NOT ALLOWING US FOR **IMAGE INPUTS**
        if "image" in userMsg and userMsg["image"] != "":
            content = [{"type": "text", "text": currMsg["content"]},
                    {"type":"image_url", "image_url": {"url":userMsg["image"]}}]
            
            currMsg["content"] = content
            MsgSave["image"] = userMsg["image"] # for database
            print("image processing required ...")

        elif "audio" in userMsg and userMsg["audio"] != "":
            transcription = await speech2text(userMsg["audio"])
            print(transcription, type(transcription))
            
            if transcription == "":
                return JSONResponse({"err": "Failed to process audio"}) 

            currMsg["content"] = str(transcription) + currMsg["content"]

            MsgSave["audio"] = userMsg["audio"] # for database
            print("audio processing required ...")
        
        # print("USER QUERY:: ",currMsg)

        # TODO: asyncio Fire and forget task here
        # asyncio.create_task(saveUserChatInferredPersonalData())
        kb.saveUserChatInferredPersonalDataWithContext(MsgSave, shortTermMemory)

        # may need to add long-term msg for now
        msg = [sysMsg] + shortTermMemory + [currMsg]

        print("\nUSER REq ===========================================\n:",msg)

        llm = ChatOpenAI()
        gptResponse = await llm.simpleResponse(msg=msg)

        assistant = {
            "role": 'assistant',
            "content": gptResponse.content,
            "group_id": userMsg["group_id"],
            "user_id": userMsg["user_id"],
        }

        # TODO: asyncio for save to db [formate gpt response for db] not working like fire and forget
        kb.saveAssistantChatSummarizeData(assistant)
        
        return JSONResponse({"data": [assistant]})
    except Exception as e:
        print("ERROR occurred while processing chat ", e)
        return JSONResponse({"err": "Internal server error"})

# TODO: add one new route for initial user profile data
# Route("/freebie", freebieHomepage),
# WebSocketRoute("/call/freebie", handleCallFreebie),
routes = [Route("/premium", premiumHomepage),
          Route("/chat", handleChat, methods=["POST"]),
          Route("/initial/chat", handleInitialChat, methods=["POST"]),
          WebSocketRoute("/call/premium", handelCallPremium)]

app = Starlette(debug=True, routes=routes)

app.mount("/", StaticFiles(directory="src/server/static"), name="static")


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://6761b19fe00b66a324897a25--companion.netlify.app"],  # Allows all origins (you can limit this to specific domains)
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Allowed HTTP methods
    allow_headers=["*"],  # Allowed headers (you can limit this as needed)
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
