from ncatbot.app import BotClient
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    BotClient().run()


if __name__ == "__main__":
    main()