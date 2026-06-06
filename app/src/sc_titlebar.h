#ifndef SC_TITLEBAR_H
#define SC_TITLEBAR_H

#include <stdbool.h>
#include <stdint.h>
#include <SDL2/SDL.h>

/*
 * Custom Title Bar para scrcpy (SDL2, C puro)
 *
 * Layout dos botões (esquerda → direita):
 *   [📷 Screenshot] [🔊 Vol+] [🔉 Vol-]  |  [◀ Back] [⏺ Home] [▦ Recents]
 *   |  [− Minimizar] [□ Maximizar] [✕ Fechar]
 *
 * A barra tem altura TITLEBAR_HEIGHT pixels.
 * A janela deve ser criada com SDL_WINDOW_BORDERLESS.
 * O conteúdo de vídeo começa em y = TITLEBAR_HEIGHT.
 */

#define TITLEBAR_HEIGHT        36
#define TITLEBAR_BTN_W         36
#define TITLEBAR_BTN_H         TITLEBAR_HEIGHT
#define TITLEBAR_SEPARATOR_W    1

/* Cor de fundo da barra (escuro, estilo Material) */
#define TITLEBAR_BG_R          0x1A
#define TITLEBAR_BG_G          0x1A
#define TITLEBAR_BG_B          0x2E
#define TITLEBAR_BG_A          0xFF

/* Cor do botão hover */
#define TITLEBAR_HOVER_R       0x2E
#define TITLEBAR_HOVER_G       0x2E
#define TITLEBAR_HOVER_B       0x4A
#define TITLEBAR_HOVER_A       0xFF

/* Cor hover do botão fechar (vermelho) */
#define TITLEBAR_CLOSE_HOVER_R 0xC0
#define TITLEBAR_CLOSE_HOVER_G 0x20
#define TITLEBAR_CLOSE_HOVER_B 0x20
#define TITLEBAR_CLOSE_HOVER_A 0xFF

/* Cor dos ícones (texto/símbolo) */
#define TITLEBAR_ICON_R        0xE0
#define TITLEBAR_ICON_G        0xE0
#define TITLEBAR_ICON_B        0xE0
#define TITLEBAR_ICON_A        0xFF

/* Cor do separador */
#define TITLEBAR_SEP_R         0x44
#define TITLEBAR_SEP_G         0x44
#define TITLEBAR_SEP_B         0x66
#define TITLEBAR_SEP_A         0xFF

/* IDs dos botões */
typedef enum {
    SC_TITLEBAR_BTN_NONE      = -1,
    SC_TITLEBAR_BTN_SCREENSHOT =  0,
    SC_TITLEBAR_BTN_VOL_UP    =  1,
    SC_TITLEBAR_BTN_VOL_DOWN  =  2,
    /* separador de grupo aqui */
    SC_TITLEBAR_BTN_BACK      =  3,
    SC_TITLEBAR_BTN_HOME      =  4,
    SC_TITLEBAR_BTN_RECENTS   =  5,
    /* separador de grupo aqui */
    SC_TITLEBAR_BTN_MINIMIZE  =  6,
    SC_TITLEBAR_BTN_MAXIMIZE  =  7,
    SC_TITLEBAR_BTN_CLOSE     =  8,
    SC_TITLEBAR_BTN_COUNT     =  9,
} sc_titlebar_btn_id;

/* Cada botão guarda sua área de hit-test */
typedef struct {
    sc_titlebar_btn_id id;
    SDL_Rect           rect;
} sc_titlebar_btn;

/* Estado principal da barra */
typedef struct {
    SDL_Renderer *renderer;
    SDL_Window   *window;

    /* Array de botões com suas áreas */
    sc_titlebar_btn buttons[SC_TITLEBAR_BTN_COUNT];

    /* Botão sob o cursor (-1 = nenhum) */
    sc_titlebar_btn_id hovered;

    /* Drag-to-move */
    bool  dragging;
    int   drag_start_mouse_x;
    int   drag_start_mouse_y;
    int   drag_start_win_x;
    int   drag_start_win_y;

    /* Largura atual da janela (atualizado em layout) */
    int   window_width;
} sc_titlebar;

/* ------------------------------------------------------------------ */
/*  API pública                                                         */
/* ------------------------------------------------------------------ */

/**
 * Inicializa a titlebar.
 * Deve ser chamado APÓS criar a janela borderless e o renderer.
 *
 * @param tb        ponteiro para sc_titlebar a inicializar
 * @param renderer  renderer SDL da janela
 * @param window    janela SDL
 */
void sc_titlebar_init(sc_titlebar *tb,
                      SDL_Renderer *renderer,
                      SDL_Window   *window);

/**
 * Recalcula as posições dos botões quando a largura da janela muda.
 * Deve ser chamado sempre que o evento SDL_WINDOWEVENT_SIZE_CHANGED for recebido.
 *
 * @param tb    ponteiro para sc_titlebar
 * @param width nova largura da janela em pixels
 */
void sc_titlebar_layout(sc_titlebar *tb, int width);

/**
 * Renderiza a barra de título no topo da janela.
 * Chame isso a cada frame, ANTES de SDL_RenderPresent.
 *
 * @param tb ponteiro para sc_titlebar
 */
void sc_titlebar_render(sc_titlebar *tb);

/**
 * Processa um evento SDL relacionado à titlebar.
 *
 * @param tb    ponteiro para sc_titlebar
 * @param event evento SDL recebido
 * @return      sc_titlebar_btn_id do botão clicado (ou SC_TITLEBAR_BTN_NONE)
 *              Apenas retorna um valor != NONE em SDL_MOUSEBUTTONUP.
 */
sc_titlebar_btn_id sc_titlebar_handle_event(sc_titlebar *tb,
                                             const SDL_Event *event);

/**
 * Retorna true se o ponto (x, y) está dentro da titlebar.
 * Útil para impedir que cliques na barra cheguem ao vídeo.
 */
bool sc_titlebar_hit_test(const sc_titlebar *tb, int x, int y);

/**
 * Retorna o SDL_Rect que representa a área da titlebar na janela.
 */
SDL_Rect sc_titlebar_get_rect(const sc_titlebar *tb);

#endif /* SC_TITLEBAR_H */
