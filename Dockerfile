FROM python:3.6

ARG elections18_POSTGRES_PORT
ARG AP_API_BASE_URL

RUN curl -sL https://deb.nodesource.com/setup_8.x | bash -
RUN apt-get update && apt-get install -y \
    postgresql-client \
    nodejs

ADD ./requirements.txt /opt/elections18/requirements.txt
ADD ./package.json /opt/elections18/package.json
WORKDIR /opt/elections18
RUN pip install -r requirements.txt
RUN npm install
