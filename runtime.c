#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>

static int g_argc = 0;
static char **g_argv = NULL;

void sn_set_args(int argc, char **argv) { g_argc = argc; g_argv = argv; }
int64_t sn_argc(void) { return (int64_t)g_argc; }
char *sn_arg(int64_t i) {
    if (i < 0 || i >= g_argc) return strdup("");
    return strdup(g_argv[i]);
}

_Bool sn_streq(const char *a, const char *b) { return strcmp(a,b)==0; }
_Bool sn_startswith(const char *s, const char *p) { return strncmp(s,p,strlen(p))==0; }
_Bool sn_contains(const char *s, const char *p) { return strstr(s,p)!=NULL; }
int64_t sn_strlen(const char *s) { return (int64_t)strlen(s); }
int64_t sn_charat(const char *s, int64_t i) {
    size_t n = strlen(s); if (i < 0 || (size_t)i >= n) return -1; return (unsigned char)s[i];
}
char *sn_concat(const char *a, const char *b) {
    size_t na=strlen(a), nb=strlen(b); char *r=malloc(na+nb+1); if(!r) exit(2);
    memcpy(r,a,na); memcpy(r+na,b,nb+1); return r;
}
char *sn_slice(const char *s, int64_t start, int64_t len) {
    int64_t n=(int64_t)strlen(s); if(start<0) start=0; if(start>n) start=n; if(len<0) len=0; if(start+len>n) len=n-start;
    char *r=malloc((size_t)len+1); if(!r) exit(2); memcpy(r,s+start,(size_t)len); r[len]=0; return r;
}
char *sn_trim(const char *s) {
    const char *a=s; while(*a && isspace((unsigned char)*a)) a++;
    const char *b=s+strlen(s); while(b>a && isspace((unsigned char)b[-1])) b--;
    size_t n=(size_t)(b-a); char *r=malloc(n+1); if(!r) exit(2); memcpy(r,a,n); r[n]=0; return r;
}

char *sn_replace(const char *s, const char *old, const char *rep) {
    size_t ns=strlen(s), no=strlen(old), nr=strlen(rep);
    if(no==0) return strdup(s);
    size_t count=0; const char *p=s; while((p=strstr(p,old))){count++;p+=no;}
    size_t outn=ns + count*(nr-no); char *out=malloc(outn+1); if(!out) exit(2);
    char *q=out; p=s; const char *hit;
    while((hit=strstr(p,old))){size_t k=(size_t)(hit-p);memcpy(q,p,k);q+=k;memcpy(q,rep,nr);q+=nr;p=hit+no;}
    strcpy(q,p); return out;
}
int64_t sn_wordcount(const char *s) {
    int64_t n=0; int in=0; for(;*s;s++){if(isspace((unsigned char)*s)){in=0;}else if(!in){in=1;n++;}} return n;
}
char *sn_word(const char *s, int64_t idx) {
    if(idx<0) return strdup(""); int64_t cur=-1; const char *start=NULL; const char *p=s;
    while(*p){while(*p && isspace((unsigned char)*p))p++; if(!*p)break; cur++; start=p; while(*p && !isspace((unsigned char)*p))p++; if(cur==idx){size_t n=(size_t)(p-start);char *r=malloc(n+1);if(!r)exit(2);memcpy(r,start,n);r[n]=0;return r;}}
    return strdup("");
}

char *sn_firstline(const char *s) {
    const char *p=strchr(s,'\n'); size_t n=p?(size_t)(p-s):strlen(s); char *r=malloc(n+1); if(!r) exit(2); memcpy(r,s,n); r[n]=0; return r;
}
char *sn_restlines(const char *s) {
    const char *p=strchr(s,'\n'); return strdup(p?p+1:"");
}
char *sn_readfile(const char *path) {
    FILE *f=fopen(path,"rb"); if(!f) return strdup(""); fseek(f,0,SEEK_END); long n=ftell(f); rewind(f);
    char *r=malloc((size_t)n+1); if(!r) exit(2); size_t got=fread(r,1,(size_t)n,f); r[got]=0; fclose(f); return r;
}
int64_t sn_writefile(const char *path, const char *data) {
    FILE *f=fopen(path,"wb"); if(!f) return -1; size_t n=strlen(data); size_t w=fwrite(data,1,n,f); fclose(f); return (int64_t)w;
}
char *sn_readline(void) {
    char *line=NULL; size_t cap=0; ssize_t n=getline(&line,&cap,stdin); if(n<0){free(line);return strdup("");}
    while(n>0 && (line[n-1]=='\n'||line[n-1]=='\r')) line[--n]=0; return line;
}
char *sn_itoa(int64_t x) { char buf[64]; snprintf(buf,sizeof(buf),"%lld",(long long)x); return strdup(buf); }
int64_t sn_atoi(const char *s) { return strtoll(s,NULL,10); }

void sn_choice_check(int64_t n) {
    if (n != 1) {
        fprintf(stderr, "Sn choose error: expected exactly one true guard, got %lld\n", (long long)n);
        abort();
    }
}
