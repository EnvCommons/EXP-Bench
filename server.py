from openreward.environments import Server

from expbench import ExpBench

if __name__ == "__main__":
    server = Server([ExpBench])
    server.run()
