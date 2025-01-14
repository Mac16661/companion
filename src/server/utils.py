import time
import json
import base64
import aiohttp
# from asyncio import sleep
from openai import AzureOpenAI
from typing import AsyncIterator
from starlette.websockets import WebSocket
import asyncio
from typing import AsyncIterator, TypeVar
import json
from openai import OpenAI
from dotenv import load_dotenv
import os
from sentence_transformers import CrossEncoder
from sentence_transformers import SentenceTransformer

from src.server.LLM import ChatOpenAI

# Load environment variables from the .env file (if present)
load_dotenv()

SECRET_OPENAI = os.getenv('SECRET_OPENAI')
TRANSCRIPTION_URL = os.getenv('TRANSCRIPTION_URL')


T = TypeVar("T")

# TODO: Put this into env and try to use azure open ai
client = OpenAI(api_key = SECRET_OPENAI)

model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
encoder_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def getEmbeddings(query):
    try:
        embeddings = model.encode(query)
        return embeddings
    except Exception as e:
        print("ERROR ocurred while transforming query to embeddings: ",e)

def re_rank_cross_encoders(prompt: str , documents: list[str]) -> tuple[str, list[int]]:
        """Re-ranks documents using a cross-encoder model for more accurate relevance scoring.

        Uses the MS MARCO MiniLM cross-encoder model to re-rank the input documents based on
        their relevance to the query prompt. Returns the concatenated text of the top 3 most
        relevant documents along with their indices.

        Args:
            documents: List of document strings to be re-ranked.

        Returns:
            tuple: A tuple containing:
                - relevant_text (str): Concatenated text from the top 3 ranked documents
                - relevant_text_ids (list[int]): List of indices for the top ranked documents

        Raises:
            ValueError: If documents list is empty
            RuntimeError: If cross-encoder model fails to load or rank documents
        """
        try:
            relevant_text = ""
            relevant_text_ids = []

            
            ranks = encoder_model.rank(prompt, documents, top_k=3)
            for rank in ranks:
                if(rank["score"] > 1):
                  relevant_text += documents[rank["corpus_id"]]
                  relevant_text_ids.append(rank["corpus_id"])

            return relevant_text, relevant_text_ids
        except Exception as e:
            print("ERROR ocurred while re-ranking context: ",e)
        

# TODO: Real time calling socket Freebie. 
async def websocketStream(websocket: WebSocket) -> AsyncIterator[str]:
    while True:
        try:
            data = await websocket.receive_text()
            # print("Websocket inp stream -> ",data)
            yield data
        except Exception as e:
            print("Websocket stream disconnect/err:", e)
            yield {type: "input.disconnected"} # TODO: Remove it not sure about this
            break

# TODO: Real-time calling socket premium[only for premium version] BETTER ERROR HANDLING REQUIRED
async def websocket_stream(websocket: WebSocket) -> AsyncIterator[str]:
    while True:
        data = await websocket.receive_text()
        yield data

    
# TODO: Most imp function for real time calling BETTER ERROR HANDLING REQUIRED
async def amerge(**streams: AsyncIterator[T]) -> AsyncIterator[tuple[str, T]]:
    """Merge multiple streams into one stream."""
    nexts: dict[asyncio.Task, str] = {
        asyncio.create_task(anext(stream)): key for key, stream in streams.items()
    }
    while nexts:
        done, _ = await asyncio.wait(nexts, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            key = nexts.pop(task)
            stream = streams[key]
            try:
                yield key, task.result()
                nexts[asyncio.create_task(anext(stream))] = key
            except StopAsyncIteration:
                pass
            except Exception as e:
                for task in nexts:
                    task.cancel()
                raise e
            
# TODO: Change it with deepgram STT
async def speech2text(path):
    data = {
        "url": path,
    }
    try:
        # Replace 'TRANSCRIPTION_URL' with the actual URL for the transcription service
        transcription_url = TRANSCRIPTION_URL

        async with aiohttp.ClientSession() as session:
            async with session.post(
                transcription_url,
                json=data,
                headers={"Content-Type": "application/json"}
            ) as response:
                # Ensure the request was successful
                if response.status != 200:
                    print(f"Error: API responded with status {response.status}")
                    return ""

                # Parse the JSON response
                response_data = await response.json()
                print("Raw Response:", response_data)

                # Safely extract 'transcription'
                transcription = response_data.get("transcription", "")
                print("Extracted Transcription:", transcription)

                return transcription

    except aiohttp.ClientError as error:
        # Handle network-related errors
        print("Network Error while speech-to-text:", error)
        return ""

    except Exception as error:
        # Handle other unexpected errors
        print("Error while speech-to-text:", error)
        return ""

def extract_entities_and_relationships(text):
    """
        example input -> text = "USER_ID=6741fc7e5c43c5e0599c0030 I am thinking about buying an Iphone"
    """
    try:
        prompt = f"""
        Extract the entities and relationships from the following text only if text have any of these [user id( Unique identifier for each user), name (First name, last name, or nickname etc), language(Primary language spoken), interests (Hobbies, passions, or favorite topics etc), Topics user want to learn, Topics user is querying or asking, goals and objective in life and any other personal information]:
        "{text}"

        STRICTLY FOLLOW THE OUTPUT FORMAT BELOW AND IMPORTANTLY KEEP EVERYTHING IN LOWER CASE.
        Example Input: USER_ID=009932 John Doe works at OpenAI in San Francisco. He is a software engineer.
        Example Output format:
        {{"entities":[{{"name":"009932","type":"Id"}},{{"name":"john doe","type":"Person"}},{{"name":"openai","type":"Organization"}},{{"name":"san francisco", "type":"Location"}}],"relationships":[{{"subject":"009932","predicate":"belongs to","object":"john doe"}},{{"subject":"009932","predicate":"works at","object":"openai"}},{{"subject":"009932","predicate":"located in","object":"san francisco"}}]}}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use GPT-4 or GPT-3.5
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        
        # Parse the response and return it
        result = response.choices[0].message.content.strip()

        # llm = ChatOpenAI()
        # gptResponse = llm.simpleResponse(msg=[{"role": "user", "content": prompt}])
        # result=gptResponse.content.strip()
        return json.loads(result)
    except Exception as e:
        print("ERROR while fetching extracting personal data:: ",result, "\n", e)
        # print("ERROR while fetching extracting personal data", e)
        return {"entities":[], "relationships":[]}

# Used for initial chat with aarth ai
def extract_entities_and_relationships_realtime(text):
    """
        example input -> text = "USER_ID=6741fc7e5c43c5e0599c0030 I am thinking about buying an Iphone"
    """
    try:
        prompt = f"""
        Extract the entities and relationships from the following text only if text have any of these [user id( Unique identifier for each user), name (First name, last name, or nickname etc), language(Primary language spoken), interests (Hobbies, passions, or favorite topics etc),Content preferences  (type of content liked e.g., videos, images, text etc),  conversation history (previous conversations, topics discussed), location (City, state, country ), age(13, 23 etc), educational background(class 1-12, undergraduate, postgraduate, phd) , goals and objective in life and any other personal information]:
        "{text}"

        NOTE: In each and every expamle person Aarth will be asking the question. You should only eaxtract entities and relationships form the answers. Questions are just for your context 

        STRICTLY FOLLOW THE OUTPUT FORMAT BELOW AND IMPORTANTLY KEEP EVERYTHING IN LOWER CASE.
        Example Input: USER_ID=009932 Question: Hey Subhodip! Can you tell me about your education background? \n Ans: CSE graduate.
        Example Output format:
        {{"entities":[{{"name":"009932","type":"Id"}},{{"name":"cse graduate","type":"Education"}}],"relationships":[{{"subject":"009932","predicate":"is","object":"cse graduate"}}]}}

        Example Input: USER_ID=009932 Question: Hi there! I am Aarth. What is your name?. \n Ans: I am Subhodip.
        Example Output format:
        {{"entities":[{{"name":"009932","type":"Id"}},{{"name":"subhodip","type":"Person"}}],"relationships":[{{"subject":"009932","predicate":"belongs to","object":"subhodip"}}]}}

        Example Input: USER_ID=009932 Question:  Great! Can you tell me your age?. \n Ans: 23
        Example Output format:
        {{"entities":[{{"name":"009932","type":"Id"}},{{"name":"23","type":"Age"}}],"relationships":[{{"subject":"009932","predicate":"age is","object":"23"}}]}}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use GPT-4 or GPT-3.5
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        
        # Parse the response and return it
        result = response.choices[0].message.content.strip()
        return json.loads(result)
    except Exception as e:
        print("ERROR while fetching extracting personal data:: ",result, "\n", e)
        # print("ERROR while fetching extracting personal data", e)
        return {"entities":[], "relationships":[]}

