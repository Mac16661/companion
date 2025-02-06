# TODO: Put it inside knowledge_base
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from bson import ObjectId
import datetime
from src.server.utils import extract_entities_and_relationships, getEmbeddings, re_rank_cross_encoders,extract_entities_and_relationships_realtime
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tavily import TavilyClient
import requests
from bs4 import BeautifulSoup
import os


# Load environment variables from the .env file (if present)
load_dotenv()

TAVILY_CLIENT = TavilyClient(api_key=os.getenv('TAVILY_KEY'))
MONGODB_CONNECTION_URL = os.getenv('MONGODB_CONNECTION_URL')
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
AURA_INSTANCEID = os.getenv('AURA_INSTANCEID')
AURA_INSTANCENAME = os.getenv('AURA_INSTANCENAME')


REDIS_CONNECTION=""  # Short-term memory cache
MONGO_CLIENT = MongoClient(MONGODB_CONNECTION_URL, server_api=ServerApi('1'))
NEO4J_CLIENT = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


class KnowledgeBase:
    def __init__(self) -> None:
        self.mongo = MONGO_CLIENT
        self.db = self.mongo["test-companion"]
        self.chatCollection = self.db["chats"]
        self.driver = NEO4J_CLIENT
        self.vectorDB = self.mongo["Knowledge-base"]
        self.vectorCollection = self.vectorDB["books"]
        self.tavily = TAVILY_CLIENT

    def fetchContextDB(self, query, nResults: int = 50):
        try:
            embedd = getEmbeddings(query)

            pipeline = [
                {
                    '$vectorSearch': {
                        'index': 'vector_index',  # Your vector index name
                        'path': 'embedding',  # The field where vectors are stored
                        'queryVector': embedd.tolist(),  # The query vector
                        'numCandidates': 500,  # Number of candidates to retrieve
                        'limit': nResults  # Limit the number of results
                    }
                },
                {
                    '$project': {
                        'text': 1,  # Project only the 'text' field
                        'score': {'$meta': 'searchScore'},  # Include the similarity score
                        '_id': 0
                    }
                }
            ]

            results = list(self.vectorCollection.aggregate(pipeline))

            strResult = []

            for s in results:
                strResult.append(s["text"])

            relevant_text, relevant_text_ids = re_rank_cross_encoders(query, strResult)
            return relevant_text
        except Exception as e:
            print("ERROR ocurred while fetching context :",e)
            return ""
        
    
    def fetchContextWeb(self, query_text):
      try:
        response = self.tavily.search(query_text, search_depth="advanced", include_images=True)
        # print("Raw response -> ", response)

        image_res = response["images"]
        response = response["results"]

        # print("Searching internet -> ", response)
        # if response[0]['score'] < 0.81:
        #   print("WEB SEARCH SCORE < 0.81==========",response[0]['title'])
        #   return "", []

        # relevant_text, relevant_text_ids = re_rank_cross_encoders(query_text,[response[0]['title']+response[0]['content']])

        # if len(relevant_text_ids) < 1:
        #   return "",[]

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
            'Upgrade-Insecure-Requests': '1',
        }

        # Send a GET request to the website
        web_response = requests.get(response[0]['url'], headers=headers)
        soup = BeautifulSoup(web_response.content, 'html.parser')
        # Extract the content
        # page_title = soup.title.text
        all_paragraphs = soup.find_all('p')
        page_content = ""
        # print("Page Title:", page_title)
        for para in all_paragraphs:
            # print(para.text)
            page_content += para.text

        return page_content, image_res
      except Exception as e:
        print("ERROR ocurred while fetching context from web :",e)
        return ""
      
    # Fetch context from both DB and WEB
    def fetchContext(self, query):
      try:
        relevant_text = self.fetchContextDB(query)
        if(relevant_text == ""):
          relevant_text, relevant_img = self.fetchContextWeb(query)
          return relevant_text, relevant_img
        return relevant_text, []
      except Exception as e:
        print("ERROR ocurred while fetching context DB and WEB :",e)
        return "", []
        


    # Push personal data to neo4j
    def push_to_neo4j(self, user_id, entities, relationships):
        print("Pushing ot neo4j . . .")
        try:
            with self.driver.session() as session:
                # Create User Node
                session.run("""
                    MERGE (u:User {user_id: $user_id})
                """, user_id=user_id)

                # Create Entity Nodes
                for entity in entities:
                    session.run("""
                        MERGE (e:Entity {name: $name, type: $type})
                    """, name=entity['name'], type=entity['type'])

                # Create Relationships Between Entities
                for relationship in relationships:
                    rel_type = relationship['predicate'].replace(" ", "_").upper()
                    session.run(f"""
                        MATCH (a:Entity {{name: $subject}}), (b:Entity {{name: $object}})
                        MERGE (a)-[r:{rel_type}]->(b)
                    """, subject=relationship['subject'], object=relationship['object'])
        except Exception as e:
            print("ERROR ocurred while pushing personal data :",e)


    # Fetches personal user data from graph db
    def fetchPersonalData(self, user):
        try:
            with self.driver.session() as session:
                query = """
                MATCH (e:Entity {name: $name})-[r]-(connected:Entity)
                RETURN e, r, connected
                """
                result = session.run(query, name=user)
                
                relationships = ""
                for record in result:
                    relationships = relationships + " person "+str(record["r"].type)+" " + str(record["connected"]["name"])+","

                # print("personal data ----------------------------------------------------------\n",relationships)
                return relationships
        except Exception as e: 
            print("ERROR occurred while fetching personal data ", e)
            return ""
        

    # Short term fetches chat form redis(using mongo db right now) fetch the first page
    def fetchShortTermChat(self, user):
        # Check if page available in memcache or not 

        # fetch current page if not in memcache
        try:
            group_id = user["group_id"]
            user_id = user["user_id"]

            chats = list(self.chatCollection.find(
                    {"group_id": ObjectId(group_id), "user_id": ObjectId(user_id)},
                    {"role": 1, "content": 1, "_id": 0}
                ).sort("createdAt", -1 ).limit(6)) # TODO: Change this limit

            # print(type(chats)) 

            if not chats:
                print("Empty chat")
                return []
            
            # Save it to memcache 
            chats.reverse()

            return chats
        except Exception as e:
            print("ERROR while fetching short-term memory: ",e)
            return []


    # Long-term historical chats
    # TODO: Should pass as a tool so llm can fetch historical data when it needs
    def fetchHistoricalChat(self, user):
        pass

    # returns both short-term and long-term chat history 
    def fetchChatHistory(self, user):
        pass

    # It will be run as a fire and forget function.It will save user current message to mongodb(SQS) and redis cache and after that it will extract if any personal data in it on not using llm/specialized models and then push it to personalized user graph 
    def saveUserChatInferredPersonalData(self, msg):
        # TODO: Only use user current query(without historical context) to infer entities and relationship
        # extracts personal info
        id=msg["user_id"]

        # TODO: Might break here
        text = f"USER_ID={id} " + msg["content"]
        result = extract_entities_and_relationships(text)
        entities = result['entities']
        relationships = result['relationships']

        # print("\nEXTRACT PERSONAL DATA:: ", entities,"\n",relationships)

        # save personal data to neo4j
        if len(relationships) > 0:
            self.push_to_neo4j(msg["user_id"],entities, relationships)

        # Converting id from string to mongo object
        msg["user_id"] = ObjectId(msg["user_id"])
        msg["group_id"] = ObjectId(msg["group_id"])

        try:
            self.chatCollection.insert_one(msg)
        except Exception as e:
            print("ERROR while saving user msg: ",e)

    def saveUserChatInferredPersonalDataWithContext(self, msg, shortTermMemory):
        # extracts personal info
        id=msg["user_id"]
        if len(shortTermMemory) > 0:
            shortTermMemory = shortTermMemory[-1]["content"]
        else :
            shortTermMemory = ""

        # print("User id: ", id)
        # print("Question context: ",shortTermMemory)
        # print("Msg: ", msg)
        # TODO: Might break here
        text = f"USER_ID={id} Question: " + shortTermMemory + "\n Ans: " + msg["content"]
        
        result = extract_entities_and_relationships_realtime(text) # TODO: Need to change the prompt
        entities = result['entities']
        relationships = result['relationships']

        # print("\nEXTRACT PERSONAL DATA:: ", entities,"\n",relationships)

        # save personal data to neo4j
        if len(relationships) > 0:
            self.push_to_neo4j(msg["user_id"],entities, relationships)

        msg["user_id"] = ObjectId(msg["user_id"])
        msg["group_id"] = ObjectId(msg["group_id"])

        try:
            self.chatCollection.insert_one(msg)
        except Exception as e:
            print("ERROR while saving user msg: ",e)

    def saveAssistantChatSummarizeData(self, msg):
        # Lacks summarization feature
        assistant = {
            "role": 'assistant',
            "content": msg["content"],
            "group_id": ObjectId(msg["group_id"]),
            "user_id": ObjectId(msg["user_id"]),
            "image": msg.get("image", ""),
            "summery": "",
            "createdAt": datetime.datetime.now()
        }
        try:
            self.chatCollection.insert_one(assistant)
            # print("ASSISTANT: ",msg)
        except Exception as e:
            print("ERROR while saving assistant msg: ",e)





