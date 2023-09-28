# Hangar

A simple discord bot to check if there are any differences in between your ships cargohold 
and their intended state (drugs missing, no capboosters etc.). Some programming knowledge required.

## Setup

Create an `.env` file (copy `.env.example`) which includes a discord bot token and ccp application details, 
as well as your domain name for callbacks for this bot.

Then start the container with
```shell
docker-compose up -d --build hangar
```

This assumes that you run traefik as a reverse-proxy externally.
