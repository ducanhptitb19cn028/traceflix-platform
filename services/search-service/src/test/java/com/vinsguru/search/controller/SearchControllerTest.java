package com.vinsguru.search.controller;

import com.vinsguru.search.dto.TitleDto;
import com.vinsguru.search.service.SearchService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(SearchController.class)
class SearchControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private SearchService searchService;

    @Test
    void search_returnsRankedHits() throws Exception {
        when(searchService.search("matrix")).thenReturn(List.of(
                new TitleDto(8, "The Matrix", "Sci-Fi", 1999, 8.7)));

        mockMvc.perform(get("/api/search").param("q", "matrix"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$[0].name").value("The Matrix"));
    }

    @Test
    void search_emptyQueryReturnsOk() throws Exception {
        when(searchService.search("")).thenReturn(List.of());

        mockMvc.perform(get("/api/search"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.length()").value(0));
    }

}
