# TODO: LLM streaming api. Move it to llm_streaming folder
import json
from openai import OpenAI
from openai import AzureOpenAI
# from src.server.KB import KnowledgeBase
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Literal, List
import os

# Load environment variables from the .env file (if present)
load_dotenv()

AZURE_API_KEY = os.getenv('AZURE_API_KEY')
AZURE_API_VERSION = os.getenv('AZURE_API_VERSION') 
AZURE_API_ENDPOINT = os.getenv('AZURE_API_ENDPOINT')

SECRET_OPENAI = os.getenv('SECRET_OPENAI')
# Initialize OpenAI Client
client = OpenAI(api_key = SECRET_OPENAI)


AZURE_CLIENT= AzureOpenAI(
            api_key=AZURE_API_KEY,  
            api_version=AZURE_API_VERSION,
            azure_endpoint =AZURE_API_ENDPOINT
        )

class UnderstandResponse(BaseModel):
   definition: str
   detailed_explanation: str
   analogies_and_examples: str
   suggested_questions: List[str]

# NOT USING OPEN AI SERVICE. WEA ARE USING AZURE OPEN AI SERVICE
class ChatAzureOpenAI():
    def __init__(self, model="gpt-4o-mini") -> None:
        self.client = AZURE_CLIENT
        self.model=model

    async def simpleResponse(self, msg):
        # Message contains system msg, chat history and user current query
        completion = self.client.chat.completions.create(model=self.model, messages=msg, max_tokens=5000, temperature=0.1)
        return completion.choices[0].message # .content

    async def streamResponse(self, msg, completeAns="", completeSentence=""):
        completion = await self.client.chat.completions.create(model=self.model, messages=msg, stream=True, max_tokens=500, temperature=0)
        for line in completion:
            # print("####################################### ", line)
            if len(line.choices) != 0:
                if line.choices[0].delta.content != None:
                    if line.choices[0].delta.content in ["." ,"?" , "!"]:
                        yield json.dumps({"content": completeSentence + line.choices[0].delta.content, "status": "success"})
                        completeAns = completeAns + line.choices[0].delta.content
                        completeSentence = ""
                    else:
                        completeSentence = completeSentence + line.choices[0].delta.content
                        completeAns = completeAns + line.choices[0].delta.content

        yield json.dumps({"content":completeAns, "status": "completed"})
            

class ChatOpenAI:
    def __init__(self, model="gpt-4o-mini") -> None:
        self.model = model

    def simpleResponse(self, query):
        msg = [
           {"role": "system", "content": "Primary Purpose: You are designed exclusively for casual, friendly conversation. Your role is to engage in light, informal chats—no academic or technical topics allowed. Handling Greetings and Casual Inquiries: Respond when the message is a simple greeting or a light question (e.g., 'Hi', 'Hello', 'Hey', 'What can you do for me?', 'How are you today?') using warm, friendly, and informal language that feels natural and welcoming. Handling Academic or Technical Questions: If the message is about any academic topic, technical subject, or anything beyond casual conversation, return an empty string. Remember, your sole purpose is to engage in casual, friendly conversation—academic or technical discussions are outside your scope. Style Guidelines: Keep responses brief, engaging, and relaxed; avoid complex language or professional jargon; maintain a casual tone that invites friendly interaction. Examples: Input: 'Hello!' → Output: 'Hey there! How’s it going?' Input: 'What can you do for me?' → Output: 'I'm here to chat and have a fun, friendly conversation with you!' Input: 'Can you explain how photosynthesis works?' → Output: (empty string)."},
           {"role": "user", "content": query},
       ]
        # Message contains system message, chat history, and user current query
        completion = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=msg,
            max_tokens=200,
            temperature=0
        )
        return completion.choices[0].message, []
    


    def simpleResponseWithToolCall(self, msg, kb, activeButton):
        # Message contains system message, chat history, and user current query
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini-2024-07-18",
            messages=msg,
            max_tokens=1000,
            temperature=0.1,
            response_format=UnderstandResponse,
            functions=[
                {
                    'name': "web_search_tool",
                    'description': "Searches the real-time web and provides more information about topics",
                    'parameters': {
                        'type': "object",
                        'properties': {
                            'query': {
                                'type': "string",
                                'description': "Query from the user",
                            },
                        },
                        'required': ["query"],  
                    }
                },
            ],
            function_call='auto'
        )

        response_message = completion.choices[0].message

        print(response_message)

        if dict(response_message).get('function_call'):
            function_called = response_message.function_call.name
            function_args = response_message.function_call.arguments
            function_args = json.loads(function_args)["query"]

            if(function_called == "web_search_tool"):
                context,imgs,revelant_link = kb.fetchContext(function_args, activeButton)
                msg[-1]["content"] = f"Context: {context}" + msg[-1]["content"]


                # Call simpleResponse function instead of this
                completion = client.beta.chat.completions.parse(
                model="gpt-4o-mini-2024-07-18",
                messages=msg,
                max_tokens=1000,
                temperature=0.1,
                response_format=UnderstandResponse
                )

                return completion.choices[0].message, imgs, revelant_link

        else: # If no function call jus return the statement
            return response_message, [], []

# TODO: For realtime audio conversion 
    async def streamResponse(self, msg, completeAns="", completeSentence=""):
        completion = await self.client.chat.completions.create(model=self.model, messages=msg, stream=True, max_tokens=500, temperature=0)
        for line in completion:
            # print("####################################### ", line)
            if len(line.choices) != 0:
                if line.choices[0].delta.content != None:
                    if line.choices[0].delta.content in ["." ,"?" , "!"]:
                        yield json.dumps({"content": completeSentence + line.choices[0].delta.content, "status": "success"})
                        completeAns = completeAns + line.choices[0].delta.content
                        completeSentence = ""
                    else:
                        completeSentence = completeSentence + line.choices[0].delta.content
                        completeAns = completeAns + line.choices[0].delta.content

        yield json.dumps({"content":completeAns, "status": "completed"})