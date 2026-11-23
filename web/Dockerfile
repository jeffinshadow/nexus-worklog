# "stable" e não uma versão fixa: o deploy.sh (build --pull) traz as correções da linha estável.
FROM nginx:stable-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY static/ /usr/share/nginx/html/

EXPOSE 80
