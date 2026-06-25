package com.vinsguru.catalog.controller;

import com.vinsguru.catalog.dto.TitleDto;
import com.vinsguru.catalog.service.CatalogService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(CatalogController.class)
class CatalogControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private CatalogService catalogService;

    @Test
    void listAll_returnsTitles() throws Exception {
        when(catalogService.listAll()).thenReturn(List.of(
                new TitleDto(1, "Inception", "Sci-Fi", 2010, 8.8)));

        mockMvc.perform(get("/api/catalog"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$[0].name").value("Inception"))
               .andExpect(jsonPath("$[0].genre").value("Sci-Fi"));
    }

    @Test
    void byId_returnsTitleWhenPresent() throws Exception {
        when(catalogService.getTitle(1))
                .thenReturn(Optional.of(new TitleDto(1, "Inception", "Sci-Fi", 2010, 8.8)));

        mockMvc.perform(get("/api/catalog/1"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.rating").value(8.8));
    }

    @Test
    void byId_returns404WhenMissing() throws Exception {
        when(catalogService.getTitle(99)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/catalog/99"))
               .andExpect(status().isNotFound());
    }

    @Test
    void search_returnsMatches() throws Exception {
        when(catalogService.search("sci")).thenReturn(List.of(
                new TitleDto(1, "Inception", "Sci-Fi", 2010, 8.8)));

        mockMvc.perform(get("/api/catalog/search").param("q", "sci"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$[0].name").value("Inception"));
    }

}
