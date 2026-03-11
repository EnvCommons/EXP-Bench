import json
import asyncio
import os

from openai import AsyncOpenAI
from openreward import AsyncOpenReward

async def main():
    or_client = AsyncOpenReward()
    oai_client = AsyncOpenAI()

    MODEL_NAME = "gpt-5.2"
    ENV_NAME = "GeneralReasoning/ExpBench"
    SPLIT = "test"
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENREWARD_API_KEY = os.getenv("OPENREWARD_API_KEY")

    environment = or_client.environments.get(name=ENV_NAME, base_url="http://localhost:8080")
    tasks = await environment.list_tasks(split=SPLIT)
    tools = await environment.list_tools(format="openai")

    print(f"Found {len(tasks)} tasks")

    for task in tasks[:1]:
        async with environment.session(
            task=task,
            secrets={
                "api_key": OPENREWARD_API_KEY,
                "openai_api_key": OPENAI_API_KEY,
            },
        ) as session:
            prompt = await session.get_prompt()
            input_list = [{"role": "user", "content": prompt[0].text}]
            finished = False

            while not finished:
                response = await oai_client.responses.create(
                    model=MODEL_NAME,
                    tools=tools,
                    input=input_list,
                )

                input_list += response.output

                for item in response.output:
                    if item.type == "function_call":
                        tool_result = await session.call_tool(
                            item.name, json.loads(str(item.arguments))
                        )

                        finished = tool_result.finished

                        input_list.append({
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": tool_result.blocks[0].text,
                        })
                        print(input_list)

                        print(f"Tool: {item.name} | Reward: {tool_result.reward}")

                        if tool_result.finished:
                            print("FINISHED!")
                            break

if __name__ == "__main__":
    asyncio.run(main())
