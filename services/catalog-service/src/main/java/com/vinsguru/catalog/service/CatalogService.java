package com.vinsguru.catalog.service;

import com.vinsguru.catalog.dto.TitleDto;
import com.vinsguru.catalog.mapper.EntityDtoMapper;
import com.vinsguru.catalog.repository.TitleRepository;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class CatalogService {

    private final TitleRepository repository;

    public CatalogService(TitleRepository repository) {
        this.repository = repository;
    }

    public List<TitleDto> listAll() {
        return this.repository.findAll()
                              .stream()
                              .map(EntityDtoMapper::toDto)
                              .toList();
    }

    public Optional<TitleDto> getTitle(Integer id) {
        return this.repository.findById(id)
                              .map(EntityDtoMapper::toDto);
    }

    public List<TitleDto> search(String query) {
        var q = query == null ? "" : query;
        return this.repository
                .findByNameContainingIgnoreCaseOrGenreContainingIgnoreCase(q, q)
                .stream()
                .map(EntityDtoMapper::toDto)
                .toList();
    }

}
