/*
 * sc_titlebar.c — Custom title bar para scrcpy (SDL2, C puro)
 *
 * Desenha uma barra de título personalizada dentro da janela borderless do
 * scrcpy, com os seguintes botões:
 *
 *  [📷 Screenshot] [🔊 Vol+] [🔉 Vol-]  |  [◀ Back] [⏺ Home] [▦ Recents]
 *  |  [− Minimize] [□ Maximize] [✕ Close]
 *
 * Os ícones são desenhados em primitivas SDL (linhas/retângulos) sem depender
 * de nenhuma fonte ou biblioteca de imagem externa.
 *
 * Como integrar ao screen.c:
 *  1. Adicione SDL_WINDOW_BORDERLESS em window_flags no sc_screen_init().
 *  2. Declare um campo  sc_titlebar titlebar;  em struct sc_screen (screen.h).
 *  3. Após criar o renderer, chame sc_titlebar_init().
 *  4. No evento SDL_WINDOWEVENT_SIZE_CHANGED, chame sc_titlebar_layout().
 *  5. Antes de SDL_RenderPresent, chame sc_titlebar_render().
 *  6. No início de sc_screen_handle_event(), passe o evento para
 *     sc_titlebar_handle_event() e reaja ao botão retornado.
 *  7. Em sc_screen_update_content_rect(), some TITLEBAR_HEIGHT ao rect->y e
 *     subtraia-o de rect->h para o vídeo não sobrepor a barra.
 */

#include "sc_titlebar.h"

#include <string.h>

/* ------------------------------------------------------------------ */
/*  Helpers de desenho de ícones (primitivas SDL)                       */
/* ------------------------------------------------------------------ */

/* Preenche um SDL_Rect inteiro com a cor atual */
static void fill_rect(SDL_Renderer *r, int x, int y, int w, int h) {
    SDL_Rect rc = {x, y, w, h};
    SDL_RenderFillRect(r, &rc);
}

/* Desenha um segmento de linha */
static void draw_line(SDL_Renderer *r, int x1, int y1, int x2, int y2) {
    SDL_RenderDrawLine(r, x1, y1, x2, y2);
}

/*
 * Ícone: câmera fotográfica (📷)
 * Desenhado como retângulo de corpo + trapézio do visor + círculo central.
 * cx, cy = centro do botão; sz = tamanho base (aprox. 14px)
 */
static void draw_icon_screenshot(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    int qs = sz / 4;
    /* Corpo da câmera */
    int bx = cx - hs;
    int by = cy - qs;
    fill_rect(r, bx, by, sz, sz);
    /* "Visor" (triângulo simplificado como um rect menor acima) */
    fill_rect(r, cx - qs, by - qs, qs, qs);
    /* Apagar o centro para simular a lente */
    SDL_SetRenderDrawColor(r, TITLEBAR_BG_R, TITLEBAR_BG_G,
                              TITLEBAR_BG_B, TITLEBAR_BG_A);
    fill_rect(r, cx - qs + 2, by + 3, qs * 2 - 4, qs * 2 - 4);
    /* Restaurar a cor do ícone */
    SDL_SetRenderDrawColor(r, TITLEBAR_ICON_R, TITLEBAR_ICON_G,
                              TITLEBAR_ICON_B, TITLEBAR_ICON_A);
    /* Anel externo da lente (quadrado vazio) */
    SDL_Rect lens = {cx - qs + 1, by + 2, qs * 2 - 2, qs * 2 - 2};
    SDL_RenderDrawRect(r, &lens);
}

/*
 * Ícone: volume alto (🔊)
 * Alto-falante + ondas à direita.
 */
static void draw_icon_vol_up(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    int qs = sz / 4;
    /* Corpo do alto-falante */
    fill_rect(r, cx - hs, cy - qs, sz / 3, qs * 2);
    /* Cone (triângulo) */
    for (int i = 0; i < qs; i++) {
        draw_line(r,
                  cx - hs + sz / 3, cy - qs + i,
                  cx - hs + sz / 3 + i, cy - qs + i);
        draw_line(r,
                  cx - hs + sz / 3, cy + qs - i,
                  cx - hs + sz / 3 + i, cy + qs - i);
    }
    /* Ondas sonoras: 2 arcos aproximados como linhas verticais curtas */
    int ox = cx - hs + sz / 3 + qs + 1;
    draw_line(r, ox, cy - qs + 2, ox, cy + qs - 2);       /* onda curta */
    draw_line(r, ox + 3, cy - qs, ox + 3, cy + qs);        /* onda longa */
}

/*
 * Ícone: volume baixo (🔉)
 * Alto-falante + uma onda menor.
 */
static void draw_icon_vol_down(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    int qs = sz / 4;
    /* Corpo do alto-falante */
    fill_rect(r, cx - hs, cy - qs, sz / 3, qs * 2);
    /* Cone */
    for (int i = 0; i < qs; i++) {
        draw_line(r,
                  cx - hs + sz / 3, cy - qs + i,
                  cx - hs + sz / 3 + i, cy - qs + i);
        draw_line(r,
                  cx - hs + sz / 3, cy + qs - i,
                  cx - hs + sz / 3 + i, cy + qs - i);
    }
    /* Apenas uma onda curta */
    int ox = cx - hs + sz / 3 + qs + 1;
    draw_line(r, ox, cy - qs + 3, ox, cy + qs - 3);
}

/*
 * Ícone: back (◀)
 * Triângulo apontando para a esquerda.
 */
static void draw_icon_back(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    int qs = sz / 4;
    for (int i = 0; i <= qs; i++) {
        draw_line(r, cx - qs + i, cy - i, cx - qs + i, cy + i);
        draw_line(r, cx + hs - i, cy - hs + i, cx + hs - i, cy + hs - i);
    }
    /* Desenho mais simples: seta composta de linhas */
    draw_line(r, cx + qs, cy - qs, cx - qs, cy);
    draw_line(r, cx - qs,      cy, cx + qs, cy + qs);
    draw_line(r, cx + qs, cy - qs, cx + qs, cy + qs);
}

/*
 * Ícone: home / círculo (⏺)
 * Círculo preenchido.
 */
static void draw_icon_home(SDL_Renderer *r, int cx, int cy, int sz) {
    /* Aproximação de círculo com retângulos sobrepostos */
    int radius = sz / 3;
    for (int dy = -radius; dy <= radius; dy++) {
        int hw = (int)SDL_sqrt((double)(radius * radius - dy * dy));
        draw_line(r, cx - hw, cy + dy, cx + hw, cy + dy);
    }
}

/*
 * Ícone: recents / grade (▦)
 * 4 quadradinhos em 2×2.
 */
static void draw_icon_recents(SDL_Renderer *r, int cx, int cy, int sz) {
    int qs = sz / 4;
    int gap = 2;
    /* superior-esquerdo */
    fill_rect(r, cx - qs - gap, cy - qs - gap, qs, qs);
    /* superior-direito */
    fill_rect(r, cx + gap, cy - qs - gap, qs, qs);
    /* inferior-esquerdo */
    fill_rect(r, cx - qs - gap, cy + gap, qs, qs);
    /* inferior-direito */
    fill_rect(r, cx + gap, cy + gap, qs, qs);
}

/*
 * Ícone: minimizar (−)
 * Linha horizontal na parte inferior da área do ícone.
 */
static void draw_icon_minimize(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    int y  = cy + hs / 2;
    fill_rect(r, cx - hs, y, sz, 2);
}

/*
 * Ícone: maximizar (□)
 * Retângulo vazio.
 */
static void draw_icon_maximize(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    SDL_Rect rc = {cx - hs, cy - hs, sz, sz};
    SDL_RenderDrawRect(r, &rc);
    /* borda dupla no topo (barra de título estilizada) */
    SDL_RenderDrawLine(r, cx - hs, cy - hs + 2, cx + hs - 1, cy - hs + 2);
}

/*
 * Ícone: fechar (✕)
 * Dois diagonais cruzados.
 */
static void draw_icon_close(SDL_Renderer *r, int cx, int cy, int sz) {
    int hs = sz / 2;
    draw_line(r, cx - hs, cy - hs, cx + hs, cy + hs);
    draw_line(r, cx + hs, cy - hs, cx - hs, cy + hs);
    /* espessura dupla */
    draw_line(r, cx - hs + 1, cy - hs, cx + hs, cy + hs - 1);
    draw_line(r, cx + hs - 1, cy - hs, cx - hs, cy + hs - 1);
}

/* ------------------------------------------------------------------ */
/*  Layout                                                              */
/* ------------------------------------------------------------------ */

/*
 * Define a ordem e posição de cada botão.
 *
 * Os botões de controle do dispositivo ficam alinhados à ESQUERDA.
 * Os botões de janela (min/max/close) ficam alinhados à DIREITA.
 *
 * Separadores são posições sem botão que criam espaço visual.
 */
void sc_titlebar_layout(sc_titlebar *tb, int width) {
    tb->window_width = width;

    /*
     * Grupo esquerdo: Screenshot | Vol+ | Vol- | sep | Back | Home | Recents
     * Posicionamento: cresce da esquerda para a direita
     */
    int x = 0;
    int y = 0;
    int h = TITLEBAR_HEIGHT;
    int bw = TITLEBAR_BTN_W;

    /* Botão Screenshot */
    tb->buttons[SC_TITLEBAR_BTN_SCREENSHOT].id   = SC_TITLEBAR_BTN_SCREENSHOT;
    tb->buttons[SC_TITLEBAR_BTN_SCREENSHOT].rect = (SDL_Rect){x, y, bw, h};
    x += bw;

    /* Botão Vol+ */
    tb->buttons[SC_TITLEBAR_BTN_VOL_UP].id   = SC_TITLEBAR_BTN_VOL_UP;
    tb->buttons[SC_TITLEBAR_BTN_VOL_UP].rect = (SDL_Rect){x, y, bw, h};
    x += bw;

    /* Botão Vol- */
    tb->buttons[SC_TITLEBAR_BTN_VOL_DOWN].id   = SC_TITLEBAR_BTN_VOL_DOWN;
    tb->buttons[SC_TITLEBAR_BTN_VOL_DOWN].rect = (SDL_Rect){x, y, bw, h};
    x += bw;

    /* Separador visual (apenas espaço) */
    x += TITLEBAR_SEPARATOR_W + 6;

    /* Botão Back */
    tb->buttons[SC_TITLEBAR_BTN_BACK].id   = SC_TITLEBAR_BTN_BACK;
    tb->buttons[SC_TITLEBAR_BTN_BACK].rect = (SDL_Rect){x, y, bw, h};
    x += bw;

    /* Botão Home */
    tb->buttons[SC_TITLEBAR_BTN_HOME].id   = SC_TITLEBAR_BTN_HOME;
    tb->buttons[SC_TITLEBAR_BTN_HOME].rect = (SDL_Rect){x, y, bw, h};
    x += bw;

    /* Botão Recents */
    tb->buttons[SC_TITLEBAR_BTN_RECENTS].id   = SC_TITLEBAR_BTN_RECENTS;
    tb->buttons[SC_TITLEBAR_BTN_RECENTS].rect = (SDL_Rect){x, y, bw, h};

    /*
     * Grupo direito: alinhado à direita
     * Ordem visual (direita → esquerda): Close | Maximize | Minimize
     */
    x = width; /* começa do lado direito */

    /* Botão Close */
    x -= bw;
    tb->buttons[SC_TITLEBAR_BTN_CLOSE].id   = SC_TITLEBAR_BTN_CLOSE;
    tb->buttons[SC_TITLEBAR_BTN_CLOSE].rect = (SDL_Rect){x, y, bw, h};

    /* Botão Maximize */
    x -= bw;
    tb->buttons[SC_TITLEBAR_BTN_MAXIMIZE].id   = SC_TITLEBAR_BTN_MAXIMIZE;
    tb->buttons[SC_TITLEBAR_BTN_MAXIMIZE].rect = (SDL_Rect){x, y, bw, h};

    /* Botão Minimize */
    x -= bw;
    tb->buttons[SC_TITLEBAR_BTN_MINIMIZE].id   = SC_TITLEBAR_BTN_MINIMIZE;
    tb->buttons[SC_TITLEBAR_BTN_MINIMIZE].rect = (SDL_Rect){x, y, bw, h};
}

/* ------------------------------------------------------------------ */
/*  Init                                                                */
/* ------------------------------------------------------------------ */

void sc_titlebar_init(sc_titlebar *tb,
                      SDL_Renderer *renderer,
                      SDL_Window   *window) {
    memset(tb, 0, sizeof(*tb));
    tb->renderer = renderer;
    tb->window   = window;
    tb->hovered  = SC_TITLEBAR_BTN_NONE;
    tb->dragging = false;

    /* Layout inicial */
    int w, h;
    SDL_GetWindowSize(window, &w, &h);
    sc_titlebar_layout(tb, w);
}

/* ------------------------------------------------------------------ */
/*  Hit-test auxiliar                                                   */
/* ------------------------------------------------------------------ */

bool sc_titlebar_hit_test(const sc_titlebar *tb, int x, int y) {
    return (y >= 0 && y < TITLEBAR_HEIGHT &&
            x >= 0 && x < tb->window_width);
}

SDL_Rect sc_titlebar_get_rect(const sc_titlebar *tb) {
    SDL_Rect r = {0, 0, tb->window_width, TITLEBAR_HEIGHT};
    return r;
}

/*
 * Retorna o botão cujo rect contém (x, y), ou SC_TITLEBAR_BTN_NONE.
 */
static sc_titlebar_btn_id find_button_at(const sc_titlebar *tb, int x, int y) {
    if (!sc_titlebar_hit_test(tb, x, y)) {
        return SC_TITLEBAR_BTN_NONE;
    }
    for (int i = 0; i < SC_TITLEBAR_BTN_COUNT; i++) {
        const SDL_Rect *rc = &tb->buttons[i].rect;
        if (x >= rc->x && x < rc->x + rc->w &&
            y >= rc->y && y < rc->y + rc->h) {
            return tb->buttons[i].id;
        }
    }
    return SC_TITLEBAR_BTN_NONE;
}

/* ------------------------------------------------------------------ */
/*  Render                                                              */
/* ------------------------------------------------------------------ */

void sc_titlebar_render(sc_titlebar *tb) {
    SDL_Renderer *r = tb->renderer;

    /* 1. Fundo da barra */
    SDL_SetRenderDrawColor(r, TITLEBAR_BG_R, TITLEBAR_BG_G,
                              TITLEBAR_BG_B, TITLEBAR_BG_A);
    SDL_Rect bar = {0, 0, tb->window_width, TITLEBAR_HEIGHT};
    SDL_RenderFillRect(r, &bar);

    /* 2. Separadores verticais */
    SDL_SetRenderDrawColor(r, TITLEBAR_SEP_R, TITLEBAR_SEP_G,
                              TITLEBAR_SEP_B, TITLEBAR_SEP_A);
    /* Separador entre grupo media e navegação */
    int sep1_x = tb->buttons[SC_TITLEBAR_BTN_VOL_DOWN].rect.x
               + tb->buttons[SC_TITLEBAR_BTN_VOL_DOWN].rect.w + 3;
    SDL_RenderDrawLine(r, sep1_x, 6, sep1_x, TITLEBAR_HEIGHT - 6);

    /* Separador entre navegação e janela */
    int sep2_x = tb->buttons[SC_TITLEBAR_BTN_MINIMIZE].rect.x - 3;
    SDL_RenderDrawLine(r, sep2_x, 6, sep2_x, TITLEBAR_HEIGHT - 6);

    /* 3. Botões: fundo de hover e ícone */
    for (int i = 0; i < SC_TITLEBAR_BTN_COUNT; i++) {
        const sc_titlebar_btn *btn = &tb->buttons[i];
        const SDL_Rect *rc = &btn->rect;

        /* Fundo hover */
        if (btn->id == tb->hovered) {
            if (btn->id == SC_TITLEBAR_BTN_CLOSE) {
                SDL_SetRenderDrawColor(r, TITLEBAR_CLOSE_HOVER_R,
                                         TITLEBAR_CLOSE_HOVER_G,
                                         TITLEBAR_CLOSE_HOVER_B,
                                         TITLEBAR_CLOSE_HOVER_A);
            } else {
                SDL_SetRenderDrawColor(r, TITLEBAR_HOVER_R, TITLEBAR_HOVER_G,
                                         TITLEBAR_HOVER_B, TITLEBAR_HOVER_A);
            }
            SDL_RenderFillRect(r, rc);
        }

        /* Ícone — centralizado dentro do botão */
        int cx = rc->x + rc->w / 2;
        int cy = rc->y + rc->h / 2;
        int icon_sz = 10; /* tamanho base do ícone */

        SDL_SetRenderDrawColor(r, TITLEBAR_ICON_R, TITLEBAR_ICON_G,
                                  TITLEBAR_ICON_B, TITLEBAR_ICON_A);

        switch (btn->id) {
        case SC_TITLEBAR_BTN_SCREENSHOT:
            draw_icon_screenshot(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_VOL_UP:
            draw_icon_vol_up(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_VOL_DOWN:
            draw_icon_vol_down(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_BACK:
            draw_icon_back(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_HOME:
            draw_icon_home(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_RECENTS:
            draw_icon_recents(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_MINIMIZE:
            draw_icon_minimize(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_MAXIMIZE:
            draw_icon_maximize(r, cx, cy, icon_sz);
            break;
        case SC_TITLEBAR_BTN_CLOSE:
            draw_icon_close(r, cx, cy, icon_sz);
            break;
        default:
            break;
        }
    }

    /* 4. Linha separadora na base da barra (borda inferior sutil) */
    SDL_SetRenderDrawColor(r, TITLEBAR_SEP_R, TITLEBAR_SEP_G,
                              TITLEBAR_SEP_B, TITLEBAR_SEP_A);
    SDL_RenderDrawLine(r, 0, TITLEBAR_HEIGHT - 1,
                          tb->window_width, TITLEBAR_HEIGHT - 1);
}

/* ------------------------------------------------------------------ */
/*  Eventos                                                             */
/* ------------------------------------------------------------------ */

sc_titlebar_btn_id sc_titlebar_handle_event(sc_titlebar *tb,
                                             const SDL_Event *event) {
    switch (event->type) {

    case SDL_MOUSEMOTION: {
        int x = event->motion.x;
        int y = event->motion.y;

        /* Drag da janela */
        if (tb->dragging) {
            int dx = x - tb->drag_start_mouse_x;
            int dy = y - tb->drag_start_mouse_y;
            SDL_SetWindowPosition(tb->window,
                                  tb->drag_start_win_x + dx,
                                  tb->drag_start_win_y + dy);
        }

        /* Hover */
        tb->hovered = find_button_at(tb, x, y);
        break;
    }

    case SDL_MOUSEBUTTONDOWN: {
        if (event->button.button != SDL_BUTTON_LEFT) {
            break;
        }
        int x = event->button.x;
        int y = event->button.y;

        if (!sc_titlebar_hit_test(tb, x, y)) {
            break;
        }

        sc_titlebar_btn_id btn = find_button_at(tb, x, y);

        if (btn == SC_TITLEBAR_BTN_NONE) {
            /* Clicou na área de drag (sem botão) → inicia drag */
            tb->dragging = true;
            tb->drag_start_mouse_x = x;
            tb->drag_start_mouse_y = y;
            SDL_GetWindowPosition(tb->window,
                                  &tb->drag_start_win_x,
                                  &tb->drag_start_win_y);
        }
        break;
    }

    case SDL_MOUSEBUTTONUP: {
        if (event->button.button != SDL_BUTTON_LEFT) {
            break;
        }

        /* Parar drag */
        if (tb->dragging) {
            tb->dragging = false;
        }

        int x = event->button.x;
        int y = event->button.y;

        if (!sc_titlebar_hit_test(tb, x, y)) {
            break;
        }

        sc_titlebar_btn_id btn = find_button_at(tb, x, y);
        if (btn != SC_TITLEBAR_BTN_NONE) {
            return btn; /* Botão clicado */
        }
        break;
    }

    case SDL_WINDOWEVENT:
        if (event->window.event == SDL_WINDOWEVENT_SIZE_CHANGED) {
            sc_titlebar_layout(tb, event->window.data1);
        }
        if (event->window.event == SDL_WINDOWEVENT_LEAVE) {
            tb->hovered  = SC_TITLEBAR_BTN_NONE;
            tb->dragging = false;
        }
        break;

    default:
        break;
    }

    return SC_TITLEBAR_BTN_NONE;
}
