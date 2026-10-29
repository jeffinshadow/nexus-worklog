FROM nginx:1.28-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY static/ /usr/share/nginx/html/

EXPOSE 80
