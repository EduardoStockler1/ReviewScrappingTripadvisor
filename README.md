# Review Scrapper
Este software coleta _reviews_ de pontos turísticos na plataforma TripAdvisor.
Foi criado durante minha primeira Iniciação Científica, cujo produto final foi este script 
e [este artigo](https://journals-sol.s
bc.org.br/index.php/isys/article/view/3644), publicado na revista iSys.

## Instalação
1. Clone o repositório
2. Instale as dependências com `pip install -r requirements.txt`
3. Crie um arquivo 'urls.txt' com as urls dos pontos turísticos a serem analisados
4. Altere as configurações em 'config.py' caso deseje
5. Execute o script com `python main.py`

## Comportamento do script

Os dados extraídos atualmente são:
- Título
- Comentário
- Data
- Nota
- Local
- Categoria

O comportamento do script é afetado pelas configurações em 'config.py'.
No geral, para cada url em 'urls.txt', o script irá abrir um navegador, pegar todos 
os comentários da página, pular pra próxima página, e repetir até que não existam mais páginas.

Depois de determinada quantidade de comentários que forem extraídos (definida em 'config.py'), o
script irá salvar os comentários em um arquivo .csv, e então irá para a próxima url em 'urls.txt'.
Esse comportamento, além de liberar memória, ajuda a não perder todo o trabalho no caso do 
script ser encerrado abruptamente.

Os reviews serão salvos numa pasta a ser criada pelo script, em './reviews/dataatual'. O motivo 
de se utilizar a data e hora para salvar é para que não se sobrescrevam dados extraídos anteriormente.

O script também gera um arquivo de log cada vez que é executado, dando um panorama de 
tudo o que aconteceu.
