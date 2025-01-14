# TODO: LLM streaming api. Move it to llm_streaming folder
import json
from openai import OpenAI
from openai import AzureOpenAI
# from src.server.KB import KnowledgeBase
from dotenv import load_dotenv
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

    async def simpleResponse(self, msg):
        # Message contains system message, chat history, and user current query
        completion = client.chat.completions.create(
            model=self.model,
            messages=msg,
            max_tokens=600,
            temperature=0
        )
        return completion.choices[0].message  # Adjusted to match OpenAI response format

    def simpleResponseWithToolCall(self, msg, kb):
        # Message contains system message, chat history, and user current query
        completion = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=msg,
            max_tokens=600,
            temperature=0.1,
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
                        'required': ["query"],  # Correct spelling for required
                    }
                },
            ],
            function_call='auto'
        )

        response_message = completion.choices[0].message

        if dict(response_message).get('function_call'):
            function_called = response_message.function_call.name
            function_args = response_message.function_call.arguments
            function_args = json.loads(function_args)["query"]

            # print(function_args,"\n\n")

            if(function_called == "web_search_tool"):
                # kb = KB # Getting the knowledge base module
                context,imgs = kb.fetchContext(function_args)
                msg[-1]["content"] = f"Context: {context}" + msg[-1]["content"]
                # print(msg)

                # Call simpleResponse function instead of this
                completion = client.chat.completions.create(
                model="gpt-4o-mini-2024-07-18",
                messages=msg,
                max_tokens=800,
                temperature=0.1
                )

                return completion.choices[0].message, imgs

        else: # If no function call jus return the statement
            return response_message, []

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